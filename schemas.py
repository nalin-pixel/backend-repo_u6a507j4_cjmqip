"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

# Example schemas (kept for reference/demo)

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user" (lowercase of class name)
    """
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")

class Product(BaseModel):
    """
    Products collection schema
    Collection name: "product" (lowercase of class name)
    """
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")

# --------------------------------------------------
# Casino affiliate app schemas

class Casino(BaseModel):
    """Casino listing information"""
    name: str
    slug: str = Field(..., description="URL-friendly unique identifier")
    logo_url: Optional[str] = None
    affiliate_url: str = Field(..., description="Outbound affiliate URL")
    bonus_text: Optional[str] = Field(None, description="Headline bonus offer text")
    features: List[str] = Field(default_factory=list)
    supported_countries: List[str] = Field(default_factory=list)
    base_score: Optional[float] = Field(4.0, ge=0, le=5, description="Editorial base score (0-5)")
    # New descriptive fields
    pros: List[str] = Field(default_factory=list, description="Pros list shown on details page")
    cons: List[str] = Field(default_factory=list, description="Cons list shown on details page")
    payment_methods: List[str] = Field(default_factory=list, description="Supported payment methods (e.g., Visa, PayPal)")
    providers: List[str] = Field(default_factory=list, description="Game providers (e.g., NetEnt, Pragmatic Play)")
    gallery: List[str] = Field(default_factory=list, description="Optional gallery of image URLs")
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    is_published: bool = Field(default=True)

class Offer(BaseModel):
    """Specific promotions for a casino"""
    casino_slug: str
    title: str
    description: Optional[str] = None
    bonus_amount: Optional[str] = None
    wagering: Optional[str] = None
    code: Optional[str] = None

class Review(BaseModel):
    """User-submitted reviews for a casino"""
    casino_slug: str
    user_name: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    status: Literal["pending", "approved", "rejected"] = Field("approved")
    moderation_notes: Optional[str] = None

class Click(BaseModel):
    """Outbound click tracking"""
    casino_slug: str
    source: Optional[str] = Field(None, description="Where the click originated (e.g., hero, listing, details)")
    user_agent: Optional[str] = None
    ip: Optional[str] = None

# Auth / Admin
class AdminUser(BaseModel):
    email: str
    password_hash: str
    role: Literal["admin", "editor", "reviewer"] = "admin"
    is_active: bool = True

# Blog
class BlogPost(BaseModel):
    title: str
    slug: str
    cover_image: Optional[str] = None
    content: str = Field(..., description="Markdown or HTML content")
    tags: List[str] = Field(default_factory=list)
    status: Literal["draft", "published"] = "draft"
    author_email: Optional[str] = None
    published_at: Optional[datetime] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None

# Media metadata (when using GridFS or external storage)
class Media(BaseModel):
    filename: str
    content_type: Optional[str] = None
    size: Optional[int] = None
    storage: Literal["gridfs", "external"] = "gridfs"
    url: Optional[str] = Field(None, description="Public URL if using external storage; otherwise /media/{id}")
    alt: Optional[str] = None
    caption: Optional[str] = None
