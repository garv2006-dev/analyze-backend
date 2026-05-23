import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from backend.app.database import get_db
from backend.app.models.prediction import StockPrediction
from backend.app.automation.scheduler import execute_analysis_cycle

logger = logging.getLogger("Routes")
logger.setLevel(logging.INFO)

router = APIRouter()

from typing import Optional
from sqlalchemy import func
from backend.app import config

@router.get("/")
async def get_predictions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    limit: Optional[int] = Query(default=None, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Fetches paginated list of historical stock graph predictions, ordered descending by capture time."""
    logger.info(f"📥 GET /api/predictions?page={page}&page_size={page_size}&limit={limit} request received.")
    try:
        # Count total predictions
        count_query = select(func.count()).select_from(StockPrediction)
        count_result = await db.execute(count_query)
        total = count_result.scalar()

        if limit is not None:
            # Maintain backward compatibility if limit parameter is explicitly passed
            query = select(StockPrediction).order_by(StockPrediction.captured_at.desc()).limit(limit)
            active_page_size = limit
        else:
            offset = (page - 1) * page_size
            query = select(StockPrediction).order_by(StockPrediction.captured_at.desc()).offset(offset).limit(page_size)
            active_page_size = page_size

        result = await db.execute(query)
        rows = result.scalars().all()
        
        # Serialize and return
        data = [row.to_dict() for row in rows]
        
        return {
            "success": True,
            "count": len(data),
            "total": total,
            "page": page if limit is None else 1,
            "page_size": active_page_size,
            "data": data
        }
    except Exception as error:
        logger.error(f"Failed to retrieve predictions: {error}")
        raise HTTPException(
            status_code=500,
            detail="Severe database disruption occurred while retrieving prediction logs."
        )

@router.delete("/{id}")
async def delete_prediction(id: int, db: AsyncSession = Depends(get_db)):
    """Deletes a single prediction record by ID, including its associated screenshots file."""
    logger.info(f"📥 DELETE /api/predictions/{id} request received.")
    try:
        query = select(StockPrediction).where(StockPrediction.id == id)
        result = await db.execute(query)
        row = result.scalars().first()
        
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Prediction record with ID #{id} was not found."
            )
            
        # Clean up image from storage if it exists
        try:
            if row.image_path and (row.image_path.startswith("http://") or row.image_path.startswith("https://")):
                # It's a Cloudinary image, delete it asynchronously in a background thread
                from backend.app.services import cloudinary as cloudinary_service
                logger.info(f"🗑️ Deleting associated Cloudinary screenshot: {row.image_path}")
                import asyncio
                await asyncio.to_thread(cloudinary_service.delete_image, row.image_path)
            else:
                # Local screenshot file
                image_file_path = config.SCREENSHOTS_DIR / row.image_path
                if image_file_path.exists():
                    image_file_path.unlink()
                    logger.info(f"🗑️ Deleted associated local screenshot file: {image_file_path}")
        except Exception as file_err:
            logger.warning(f"Could not delete image file {row.image_path}: {file_err}")


        # Delete database row
        await db.delete(row)
        await db.commit()
        
        return {
            "success": True,
            "message": f"Prediction record #{id} and its associated screenshot deleted successfully."
        }
    except HTTPException:
        raise
    except Exception as error:
        await db.rollback()
        logger.error(f"Failed to delete prediction record #{id}: {error}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while deleting the prediction record."
        )

@router.get("/latest")
async def get_latest_prediction(db: AsyncSession = Depends(get_db)):
    """Retrieves the single most recently executed stock prediction analysis."""
    logger.info("📥 GET /api/predictions/latest request received.")
    try:
        query = select(StockPrediction).order_by(StockPrediction.captured_at.desc()).limit(1)
        result = await db.execute(query)
        row = result.scalars().first()
        
        return {
            "success": True,
            "data": row.to_dict() if row else None
        }
    except Exception as error:
        logger.error(f"Failed to retrieve latest prediction: {error}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve latest prediction."
        )

@router.get("/{id}")
async def get_prediction_by_id(id: int, db: AsyncSession = Depends(get_db)):
    """Fetches a single detailed prediction analysis by its primary key identifier."""
    logger.info(f"📥 GET /api/predictions/{id} request received.")
    try:
        query = select(StockPrediction).where(StockPrediction.id == id)
        result = await db.execute(query)
        row = result.scalars().first()
        
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Prediction record with ID #{id} was not found."
            )
            
        return {
            "success": True,
            "data": row.to_dict()
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Failed to retrieve prediction by ID: {error}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while fetching the detailed prediction record."
        )

@router.post("/trigger")
async def trigger_manual_analysis(db: AsyncSession = Depends(get_db)):
    """Manually forces an immediate Playwright capture and OpenAI Vision analysis sequence, saving the results."""
    logger.info("📥 POST /api/predictions/trigger request received. Initiating immediate automated run...")
    try:
        # Run core cycle using current db session
        prediction = await execute_analysis_cycle(db)
        await db.commit()
        
        return {
            "success": True,
            "data": prediction.to_dict()
        }
    except Exception as error:
        await db.rollback()
        logger.error(f"Manual scan cycle failed: {error}")
        raise HTTPException(
            status_code=500,
            detail=f"On-demand browser capture/AI analysis cycle failed: {error}"
        )
