import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone

from backend.app.database import get_db, get_next_sequence
from backend.app.models.saved_asset import SavedAsset

logger = logging.getLogger("Assets")
logger.setLevel(logging.INFO)

router = APIRouter()

# Default assets that are always seeded if the table is empty
DEFAULT_ASSETS = [
    {"symbol": "NIFTY50", "url": "https://groww.in/charts/indices/nifty"},
    {"symbol": "HDFC",    "url": "https://groww.in/stocks/hdfc-bank-ltd"},
    {"symbol": "JIO",     "url": "https://groww.in/stocks/jio-financial-services-ltd"},
]

class AssetCreateRequest(BaseModel):
    symbol: str
    url: str

async def _ensure_defaults(db: AsyncIOMotorDatabase):
    """Seeds the default watchlist assets the very first time the table is empty."""
    count = await db.saved_assets.count_documents({})
    if count == 0:
        for asset in DEFAULT_ASSETS:
            asset_id = await get_next_sequence("saved_assets")
            await db.saved_assets.insert_one({
                "id": asset_id,
                "symbol": asset["symbol"].upper(),
                "url": asset["url"],
                "created_at": datetime.now(timezone.utc)
            })

@router.get("/")
async def list_saved_assets(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Returns the full list of user-saved watchlist assets, seeding defaults on first run."""
    logger.info("📥 GET /api/assets request received.")
    try:
        await _ensure_defaults(db)
        cursor = db.saved_assets.find().sort("created_at", 1)
        rows_docs = await cursor.to_list(length=100)
        rows = [SavedAsset.from_dict(r) for r in rows_docs]
        return {"success": True, "data": [r.to_dict() for r in rows]}
    except Exception as e:
        logger.error(f"Failed to list saved assets: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve saved assets.")

@router.post("/")
async def create_saved_asset(body: AssetCreateRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Adds a new watchlist asset (symbol + URL) permanently to the database."""
    symbol = body.symbol.strip().upper()
    url = body.url.strip()
    logger.info(f"📥 POST /api/assets — symbol={symbol}")

    if not symbol or not url:
        raise HTTPException(status_code=400, detail="Both symbol and url are required.")

    # Check for duplicate
    existing = await db.saved_assets.find_one({"symbol": symbol})
    if existing:
        raise HTTPException(status_code=409, detail=f"Asset '{symbol}' already exists.")

    asset_id = await get_next_sequence("saved_assets")
    now = datetime.now(timezone.utc)
    new_asset_doc = {
        "id": asset_id,
        "symbol": symbol,
        "url": url,
        "created_at": now
    }
    await db.saved_assets.insert_one(new_asset_doc)
    asset = SavedAsset.from_dict(new_asset_doc)

    logger.info(f"✔️ Asset '{symbol}' saved to database.")
    return {"success": True, "data": asset.to_dict()}

@router.delete("/{symbol}")
async def delete_saved_asset(symbol: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Permanently removes a watchlist asset from the database by its symbol."""
    symbol = symbol.strip().upper()
    logger.info(f"📥 DELETE /api/assets/{symbol}")
    try:
        row = await db.saved_assets.find_one({"symbol": symbol})
        if not row:
            raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found.")
        
        await db.saved_assets.delete_one({"symbol": symbol})
        return {"success": True, "message": f"Asset '{symbol}' removed."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete asset '{symbol}': {e}")
        raise HTTPException(status_code=500, detail="Failed to delete asset.")
