import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from backend.app.database import get_db
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


async def _ensure_defaults(db: AsyncSession):
    """Seeds the default watchlist assets the very first time the table is empty."""
    count_result = await db.execute(select(SavedAsset))
    rows = count_result.scalars().all()
    if not rows:
        for asset in DEFAULT_ASSETS:
            db.add(SavedAsset(symbol=asset["symbol"].upper(), url=asset["url"]))
        await db.commit()


@router.get("/")
async def list_saved_assets(db: AsyncSession = Depends(get_db)):
    """Returns the full list of user-saved watchlist assets, seeding defaults on first run."""
    logger.info("📥 GET /api/assets request received.")
    try:
        await _ensure_defaults(db)
        result = await db.execute(select(SavedAsset).order_by(SavedAsset.created_at.asc()))
        rows = result.scalars().all()
        return {"success": True, "data": [r.to_dict() for r in rows]}
    except Exception as e:
        logger.error(f"Failed to list saved assets: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve saved assets.")


@router.post("/")
async def create_saved_asset(body: AssetCreateRequest, db: AsyncSession = Depends(get_db)):
    """Adds a new watchlist asset (symbol + URL) permanently to the database."""
    symbol = body.symbol.strip().upper()
    url = body.url.strip()
    logger.info(f"📥 POST /api/assets — symbol={symbol}")

    if not symbol or not url:
        raise HTTPException(status_code=400, detail="Both symbol and url are required.")

    # Check for duplicate
    existing = await db.execute(select(SavedAsset).where(SavedAsset.symbol == symbol))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"Asset '{symbol}' already exists.")

    asset = SavedAsset(symbol=symbol, url=url)
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    logger.info(f"✔️ Asset '{symbol}' saved to database.")
    return {"success": True, "data": asset.to_dict()}


@router.delete("/{symbol}")
async def delete_saved_asset(symbol: str, db: AsyncSession = Depends(get_db)):
    """Permanently removes a watchlist asset from the database by its symbol."""
    symbol = symbol.strip().upper()
    logger.info(f"📥 DELETE /api/assets/{symbol}")
    try:
        result = await db.execute(select(SavedAsset).where(SavedAsset.symbol == symbol))
        row = result.scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found.")
        await db.delete(row)
        await db.commit()
        return {"success": True, "message": f"Asset '{symbol}' removed."}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete asset '{symbol}': {e}")
        raise HTTPException(status_code=500, detail="Failed to delete asset.")
