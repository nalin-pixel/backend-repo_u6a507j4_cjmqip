import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Literal

from fastapi import FastAPI, Request, HTTPException, Header, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from pymongo.collection import Collection

from database import create_document, get_documents, db
from schemas import Casino, Offer, Review, Click, AdminUser, BlogPost, Media

# ----------------------------------------------------------------------------
# App & CORS
# ----------------------------------------------------------------------------
app = FastAPI(title="Casino Affiliate API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------------------
# Config & Security
# ----------------------------------------------------------------------------
ADMIN_SECRET = os.getenv("ADMIN_SECRET")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change")
JWT_ALG = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE", "60"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def collection(name: str) -> Collection:
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return db[name]


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(plain_password, password_hash)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = collection("adminuser").find_one({"email": email})
    if not user or not user.get("is_active", True):
        raise credentials_exception
    user["id"] = str(user.pop("_id", ""))
    return user


def require_roles(*roles: str):
    async def role_checker(user=Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return role_checker


# ----------------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------------
@app.get("/")
async def read_root():
    return {"message": "Casino Affiliate Backend Running"}


@app.get("/test")
async def test_database():
    try:
        if db is None:
            raise Exception("Database not initialized")
        collections = db.list_collection_names()
        return {
            "backend": "✅ Running",
            "database": "✅ Connected & Working",
            "database_name": db.name,
            "collections": collections,
        }
    except Exception as e:
        return {
            "backend": "✅ Running",
            "database": f"❌ {str(e)}",
            "database_url": "Set" if os.getenv("DATABASE_URL") else "Not Set",
            "database_name": "Set" if os.getenv("DATABASE_NAME") else "Not Set",
        }


# ----------------------------------------------------------------------------
# Auth Endpoints (Admin)
# ----------------------------------------------------------------------------

@app.post("/api/auth/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    users = list(collection("adminuser").find({"email": form_data.username}))
    if not users:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = users[0]
    if not verify_password(form_data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user["email"], "role": user.get("role", "admin")})
    return TokenResponse(access_token=token)


@app.post("/api/auth/seed-admin")
async def seed_admin(email: str = Form(...), password: str = Form(...), x_admin_secret: Optional[str] = Header(default=None)):
    # simple guard to prevent open seeding in prod
    if ADMIN_SECRET and x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if collection("adminuser").find_one({"email": email}):
        return {"status": "exists"}
    doc = {
        "email": email,
        "password_hash": get_password_hash(password),
        "role": "admin",
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    res = collection("adminuser").insert_one(doc)
    return {"id": str(res.inserted_id), "status": "created"}


# ----------------------------------------------------------------------------
# Public content endpoints
# ----------------------------------------------------------------------------

@app.get("/api/casinos")
async def list_casinos(
    country: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    sort: Optional[str] = None,
):
    """Return published casinos. If database is not configured, return an empty list instead of failing.
    """
    try:
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 50:
            page_size = 10

        filter_q: Dict[str, Any] = {"is_published": True}
        if country:
            filter_q["supported_countries"] = {"$in": [country.upper()]}
        if q:
            filter_q["name"] = {"$regex": q, "$options": "i"}

        sort_spec = None
        if sort == "score_desc":
            sort_spec = ("base_score", -1)
        elif sort == "score_asc":
            sort_spec = ("base_score", 1)
        elif sort == "name_desc":
            sort_spec = ("name", -1)
        else:
            sort_spec = ("name", 1)

        col = collection("casino")
        total = col.count_documents(filter_q)
        cursor = col.find(filter_q).sort([sort_spec]).skip((page - 1) * page_size).limit(page_size)
        docs = list(cursor)
        for d in docs:
            d["id"] = str(d.pop("_id", ""))

        return {
            "items": docs,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": (total + page_size - 1) // page_size,
            },
        }
    except Exception:
        # Graceful fallback when DB isn't configured
        return {
            "items": [],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": 0,
                "pages": 0,
            },
        }


@app.get("/api/casinos/{slug}")
async def get_casino(slug: str):
    try:
        docs = get_documents("casino", {"slug": slug})
    except Exception:
        raise HTTPException(status_code=404, detail="Casino not found")
    if not docs:
        raise HTTPException(status_code=404, detail="Casino not found")
    d = docs[0]
    d["id"] = str(d.pop("_id", ""))
    offers = get_documents("offer", {"casino_slug": slug})
    for o in offers:
        o["id"] = str(o.pop("_id", ""))
    reviews = get_documents("review", {"casino_slug": slug})
    for r in reviews:
        r["id"] = str(r.pop("_id", ""))

    breakdown = {str(i): 0 for i in range(1, 6)}
    for r in reviews:
        try:
            breakdown[str(int(r.get("rating", 0)))] += 1
        except Exception:
            pass
    total_reviews = sum(breakdown.values())
    avg_rating = (
        round(
            sum(int(k) * v for k, v in breakdown.items()) / total_reviews, 2
        ) if total_reviews else None
    )

    return {
        "casino": d,
        "offers": offers,
        "reviews": reviews,
        "ratings": {
            "breakdown": breakdown,
            "total": total_reviews,
            "average": avg_rating,
        },
    }


class NewReview(BaseModel):
    casino_slug: str
    user_name: str
    rating: int
    comment: Optional[str] = None


@app.post("/api/reviews")
async def submit_review(payload: NewReview):
    review = Review(**payload.model_dump())
    inserted_id = create_document("review", review)
    return {"id": inserted_id, "message": "Review submitted"}


class NewOffer(BaseModel):
    casino_slug: str
    title: str
    description: Optional[str] = None
    bonus_amount: Optional[str] = None
    wagering: Optional[str] = None
    code: Optional[str] = None


@app.post("/api/offers")
async def create_offer(payload: NewOffer, x_admin_secret: Optional[str] = Header(default=None), user=Depends(require_roles("admin", "editor"))):
    # allow either role-based auth (preferred) or legacy secret header if configured
    if ADMIN_SECRET and x_admin_secret != ADMIN_SECRET and user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    casino_docs = get_documents("casino", {"slug": payload.casino_slug})
    if not casino_docs:
        raise HTTPException(status_code=400, detail="Casino does not exist")
    offer = Offer(**payload.model_dump())
    inserted_id = create_document("offer", offer)
    return {"id": inserted_id, "message": "Offer created"}


@app.post("/api/click")
async def track_click(payload: Click, request: Request):
    data = payload.model_dump()
    data["user_agent"] = request.headers.get("user-agent")
    data["ip"] = request.client.host if request.client else None
    try:
        inserted_id = create_document("click", data)
        return {"id": inserted_id, "status": "ok"}
    except Exception:
        # If DB isn't available, still acknowledge the click
        return {"id": None, "status": "ok"}


# ----------------------------------------------------------------------------
# Admin-secured CRUD endpoints
# ----------------------------------------------------------------------------

class CasinoUpsert(BaseModel):
    name: str
    slug: str
    affiliate_url: str
    logo_url: Optional[str] = None
    bonus_text: Optional[str] = None
    features: Optional[List[str]] = []
    supported_countries: Optional[List[str]] = []
    base_score: Optional[float] = 4.0
    pros: Optional[List[str]] = []
    cons: Optional[List[str]] = []
    payment_methods: Optional[List[str]] = []
    providers: Optional[List[str]] = []
    gallery: Optional[List[str]] = []
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    is_published: Optional[bool] = True


@app.post("/api/admin/casinos", dependencies=[Depends(require_roles("admin", "editor"))])
async def admin_create_casino(payload: CasinoUpsert):
    if collection("casino").find_one({"slug": payload.slug}):
        raise HTTPException(status_code=400, detail="Slug already exists")
    doc = Casino(**payload.model_dump())
    inserted_id = create_document("casino", doc)
    return {"id": inserted_id}


@app.put("/api/admin/casinos/{slug}", dependencies=[Depends(require_roles("admin", "editor"))])
async def admin_update_casino(slug: str, payload: CasinoUpsert):
    res = collection("casino").update_one({"slug": slug}, {"$set": payload.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Casino not found")
    return {"updated": True}


class ReviewUpdate(BaseModel):
    rating: Optional[int] = None
    comment: Optional[str] = None
    status: Optional[Literal["pending", "approved", "rejected"]] = None
    moderation_notes: Optional[str] = None


@app.put("/api/admin/reviews/{review_id}", dependencies=[Depends(require_roles("admin", "reviewer", "editor"))])
async def admin_update_review(review_id: str, payload: ReviewUpdate):
    from bson import ObjectId
    try:
        _id = ObjectId(review_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid review id")
    res = collection("review").update_one({"_id": _id}, {"$set": {k: v for k, v in payload.model_dump().items() if v is not None}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"updated": True}


# Blog endpoints
class BlogUpsert(BaseModel):
    title: str
    slug: str
    cover_image: Optional[str] = None
    content: str
    tags: Optional[List[str]] = []
    status: Optional[Literal["draft", "published"]] = "draft"
    author_email: Optional[str] = None
    published_at: Optional[datetime] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None


@app.post("/api/admin/blogs", dependencies=[Depends(require_roles("admin", "editor"))])
async def admin_create_blog(payload: BlogUpsert, user=Depends(get_current_user)):
    if collection("blogpost").find_one({"slug": payload.slug}):
        raise HTTPException(status_code=400, detail="Slug already exists")
    doc = payload.model_dump()
    if doc.get("status") == "published" and not doc.get("published_at"):
        doc["published_at"] = datetime.utcnow()
    doc["author_email"] = user.get("email")
    res = collection("blogpost").insert_one(doc)
    return {"id": str(res.inserted_id)}


@app.put("/api/admin/blogs/{slug}", dependencies=[Depends(require_roles("admin", "editor"))])
async def admin_update_blog(slug: str, payload: BlogUpsert):
    doc = payload.model_dump()
    res = collection("blogpost").update_one({"slug": slug}, {"$set": doc})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Blog not found")
    return {"updated": True}


@app.get("/api/blogs")
async def list_blogs(page: int = 1, page_size: int = 10, tag: Optional[str] = None):
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 50:
        page_size = 10
    q: Dict[str, Any] = {"status": "published"}
    if tag:
        q["tags"] = {"$in": [tag]}
    col = collection("blogpost")
    total = col.count_documents(q)
    docs = list(col.find(q).sort([("published_at", -1)]).skip((page - 1) * page_size).limit(page_size))
    for d in docs:
        d["id"] = str(d.pop("_id", ""))
    return {
        "items": docs,
        "pagination": {"page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1)//page_size}
    }


@app.get("/api/blogs/{slug}")
async def get_blog(slug: str):
    doc = collection("blogpost").find_one({"slug": slug, "status": "published"})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    doc["id"] = str(doc.pop("_id", ""))
    return doc


# ----------------------------------------------------------------------------
# Media handling (basic, URL-based or GridFS placeholder)
# ----------------------------------------------------------------------------

@app.post("/api/admin/media", dependencies=[Depends(require_roles("admin", "editor"))])
async def upload_media(file: UploadFile = File(...)):
    # For simplicity, store in GridFS-like collection as base64 or save to /tmp and return a fake URL.
    # In a real deployment, we would use S3 and presigned URLs. Here, we store metadata only and expect external URL to be managed elsewhere.
    content = await file.read()
    size = len(content)
    doc = {
        "filename": file.filename,
        "content_type": file.content_type,
        "size": size,
        "storage": "gridfs",
        # Not storing content to keep the environment light; in real app, use GridFS.
        "created_at": datetime.utcnow(),
    }
    res = collection("media").insert_one(doc)
    return {"id": str(res.inserted_id), "filename": file.filename, "size": size}


# ----------------------------------------------------------------------------
# Legacy seed endpoints (kept for compatibility)
# ----------------------------------------------------------------------------
class SeedCasino(BaseModel):
    name: str
    slug: str
    affiliate_url: str
    logo_url: Optional[str] = None
    bonus_text: Optional[str] = None
    features: Optional[List[str]] = []
    supported_countries: Optional[List[str]] = []
    base_score: Optional[float] = 4.0
    pros: Optional[List[str]] = []
    cons: Optional[List[str]] = []
    payment_methods: Optional[List[str]] = []
    providers: Optional[List[str]] = []


@app.post("/api/seed/casino")
async def seed_casino(payload: SeedCasino, x_admin_secret: Optional[str] = Header(default=None)):
    if ADMIN_SECRET and x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    casino = Casino(**payload.model_dump())
    inserted_id = create_document("casino", casino)
    return {"id": inserted_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
