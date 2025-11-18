import os
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from database import create_document, get_documents, db
from schemas import Casino, Offer, Review, Click

app = FastAPI(title="Casino Affiliate API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_SECRET = os.getenv("ADMIN_SECRET")

@app.get("/")
def read_root():
    return {"message": "Casino Affiliate Backend Running"}

@app.get("/test")
def test_database():
    """Verify DB connectivity and show available collections"""
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

# ----------------------
# Public endpoints
# ----------------------

@app.get("/api/casinos")
async def list_casinos(
    country: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    sort: Optional[str] = None,
):
    """List casinos with optional filters and pagination
    - country: filter by supported country code (case-insensitive)
    - q: search by name (case-insensitive contains)
    - page, page_size: pagination controls
    - sort: one of [score_desc, score_asc, name_asc, name_desc]
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 50:
        page_size = 10

    filter_q: Dict[str, Any] = {}
    if country:
        filter_q["supported_countries"] = {"$in": [country.upper()]}
    if q:
        filter_q["name"] = {"$regex": q, "$options": "i"}

    # Sorting
    sort_spec = None
    if sort == "score_desc":
        sort_spec = ("base_score", -1)
    elif sort == "score_asc":
        sort_spec = ("base_score", 1)
    elif sort == "name_desc":
        sort_spec = ("name", -1)
    else:  # default name asc
        sort_spec = ("name", 1)

    # Query with pagination
    col = db["casino"]
    total = col.count_documents(filter_q)
    cursor = col.find(filter_q).sort([sort_spec]).skip((page - 1) * page_size).limit(page_size)
    docs = list(cursor)

    # Normalize
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

@app.get("/api/casinos/{slug}")
async def get_casino(slug: str):
    docs = get_documents("casino", {"slug": slug})
    if not docs:
        raise HTTPException(status_code=404, detail="Casino not found")
    d = docs[0]
    d["id"] = str(d.pop("_id", ""))
    # attach offers and recent reviews
    offers = get_documents("offer", {"casino_slug": slug})
    for o in offers:
        o["id"] = str(o.pop("_id", ""))
    reviews = get_documents("review", {"casino_slug": slug})
    for r in reviews:
        r["id"] = str(r.pop("_id", ""))

    # ratings breakdown
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
    # Basic validation is handled by Pydantic, store review
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
async def create_offer(payload: NewOffer, x_admin_secret: Optional[str] = Header(default=None)):
    # simple admin guard
    if ADMIN_SECRET and x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # ensure casino exists
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
    inserted_id = create_document("click", data)
    return {"id": inserted_id, "status": "ok"}

# Seed / create casino (admin)
class SeedCasino(BaseModel):
    name: str
    slug: str
    affiliate_url: str
    logo_url: Optional[str] = None
    bonus_text: Optional[str] = None
    features: Optional[List[str]] = []
    supported_countries: Optional[List[str]] = []
    base_score: Optional[float] = 4.0
    # Optional extended meta
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
