"""
Database Helper Functions

MongoDB helper functions ready to use in your backend code.
Import and use these functions in your API endpoints for database operations.
"""

from pymongo import MongoClient
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from typing import Union, Optional
from pydantic import BaseModel

# Load environment variables from .env file
load_dotenv()

_client: Optional[MongoClient] = None
db = None

def _connect():
    """Lazy-connect to MongoDB using env vars if not already connected."""
    global _client, db
    if db is not None:
        return db
    database_url = os.getenv("DATABASE_URL")
    database_name = os.getenv("DATABASE_NAME")
    if database_url and database_name:
        _client = MongoClient(database_url)
        db = _client[database_name]
        return db
    return None


def get_db():
    """Get a live db handle or None if env vars are not set."""
    return _connect()


# Helper functions for common database operations

def create_document(collection_name: str, data: Union[BaseModel, dict]):
    """Insert a single document with timestamp"""
    database = _connect()
    if database is None:
        raise Exception("Database not available. Check DATABASE_URL and DATABASE_NAME environment variables.")

    # Convert Pydantic model to dict if needed
    if isinstance(data, BaseModel):
        data_dict = data.model_dump()
    else:
        # make a shallow copy to avoid mutating caller's dict
        data_dict = dict(data)

    now = datetime.now(timezone.utc)
    data_dict['created_at'] = now
    data_dict['updated_at'] = now

    result = database[collection_name].insert_one(data_dict)
    return str(result.inserted_id)


def get_documents(collection_name: str, filter_dict: dict = None, limit: int = None):
    """Get documents from collection"""
    database = _connect()
    if database is None:
        raise Exception("Database not available. Check DATABASE_URL and DATABASE_NAME environment variables.")

    cursor = database[collection_name].find(filter_dict or {})
    if limit:
        cursor = cursor.limit(limit)

    return list(cursor)
