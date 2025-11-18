import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
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
async def list_casinos(country: Optional[str] = None):
    """List casinos, optionally filter by supported country code"""
    filter_q = {}
    if country:
        filter_q = {"supported_countries": {"$in": [country.upper()]}}
    docs = get_documents("casino", filter_q)
    # Normalize Mongo ObjectId for frontend consumption
    for d in docs:
        d["id"] = str(d.pop("_id", ""))
    return {"items": docs}

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
    return {"casino": d, "offers": offers, "reviews": reviews}

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

@app.post("/api/click")
async def track_click(payload: Click, request: Request):
    data = payload.model_dump()
    data["user_agent"] = request.headers.get("user-agent")
    data["ip"] = request.client.host if request.client else None
    inserted_id = create_document("click", data)
    return {"id": inserted_id, "status": "ok"}

# Seed endpoint (optional helper)
class SeedCasino(BaseModel):
    name: str
    slug: str
    affiliate_url: str
    logo_url: Optional[str] = None
    bonus_text: Optional[str] = None
    features: Optional[List[str]] = []
    supported_countries: Optional[List[str]] = []
    base_score: Optional[float] = 4.0

@app.post("/api/seed/casino")
async def seed_casino(payload: SeedCasino):
    casino = Casino(**payload.model_dump())
    inserted_id = create_document("casino", casino)
    return {"id": inserted_id}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
