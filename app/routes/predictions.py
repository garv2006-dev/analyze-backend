import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.target_url import TargetURL
from backend.app.models.screenshot import Screenshot
from backend.app.models.prediction import Prediction
from backend.app.models.log import Log
from backend.app.services.security import get_current_user
from backend.app.automation.scheduler import execute_user_monitoring_cycle, check_monitoring_hours

logger = logging.getLogger("PredictionRoutes")
logger.setLevel(logging.INFO)

router = APIRouter()

class BulkDeleteRequest(BaseModel):
    ids: list[int] = []
    delete_all: bool = False

@router.get("/")
async def get_predictions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Fetches a paginated list of predictions belonging to the authenticated User."""
    try:
        # Build query joining Prediction and Screenshot
        query = select(Prediction, Screenshot).join(Screenshot).where(
            Screenshot.user_id == current_user.id
        )
        
        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        count_res = await db.execute(count_query)
        total = count_res.scalar() or 0
        
        # Paginate and order by newest first
        offset = (page - 1) * page_size
        query = query.order_by(Prediction.timestamp.desc()).offset(offset).limit(page_size)
        
        result = await db.execute(query)
        rows = result.all()
        
        data = []
        for p, s in rows:
            data.append(p.to_dict(screenshot_path=s.image_path, highlighted_path=s.highlighted_image_path))
            
        return {
            "success": True,
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": data
        }
    except Exception as e:
        logger.error(f"Failed to fetch predictions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve predictions from database."
        )

@router.get("/latest")
async def get_latest_prediction(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Retrieves the single latest prediction analysis for the current user."""
    try:
        query = select(Prediction, Screenshot).join(Screenshot).where(
            Screenshot.user_id == current_user.id
        ).order_by(Prediction.timestamp.desc()).limit(1)
        
        result = await db.execute(query)
        row = result.first()
        
        if not row:
            return {
                "success": True,
                "data": None
            }
            
        p, s = row
        return {
            "success": True,
            "data": p.to_dict(screenshot_path=s.image_path, highlighted_path=s.highlighted_image_path)
        }
    except Exception as e:
        logger.error(f"Failed to retrieve latest prediction: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve latest prediction."
        )

@router.post("/trigger")
async def trigger_manual_analysis(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Manually triggers an immediate screenshot capture and AI prediction analysis cycle."""
    # 1. Fetch user's target URL
    url_res = await db.execute(select(TargetURL).where(TargetURL.user_id == current_user.id))
    target = url_res.scalars().first()
    
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No target URL configured. Please add a target URL first."
        )
        
    # 2. Check working hours constraint
    is_valid, current_time_str, tz_name = check_monitoring_hours()
    if not is_valid:
        # Log failure
        audit_log = Log(
            user_id=current_user.id,
            event_type="MANUAL_TRIGGER_BLOCKED",
            message=f"Attempted to trigger manual capture outside allowed hours ({current_time_str} {tz_name})."
        )
        db.add(audit_log)
        await db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Monitoring is only available between 09:15 AM and 03:15 PM {tz_name}. Current server time: {current_time_str}."
        )
        
    # 3. Execute monitoring cycle
    try:
        prediction = await execute_user_monitoring_cycle(db, target)
        
        # Load screenshot details for serialization
        screenshot_query = select(Screenshot).where(Screenshot.id == prediction.screenshot_id)
        screenshot_res = await db.execute(screenshot_query)
        screenshot = screenshot_res.scalars().first()
        
        return {
            "success": True,
            "data": prediction.to_dict(
                screenshot_path=screenshot.image_path if screenshot else None,
                highlighted_path=screenshot.highlighted_image_path if screenshot else None
            )
        }
    except Exception as e:
        logger.error(f"Manual scan cycle failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"On-demand browser capture/AI analysis cycle failed: {str(e)}"
        )

@router.delete("/{id}")
async def delete_prediction(id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Deletes a single prediction record by ID if it belongs to the current user."""
    try:
        # Check prediction ownership via Screenshot join
        query = select(Prediction).join(Screenshot).where(
            Prediction.id == id,
            Screenshot.user_id == current_user.id
        )
        result = await db.execute(query)
        prediction = result.scalars().first()
        
        if not prediction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prediction record with ID #{id} was not found."
            )
            
        await db.delete(prediction)
        await db.commit()
        
        return {
            "success": True,
            "message": f"Prediction record #{id} has been deleted."
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete prediction record #{id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the prediction record."
        )

@router.post("/bulk-delete")
async def bulk_delete_predictions(body: BulkDeleteRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Bulk deletes selected or all predictions for the current user."""
    try:
        if body.delete_all:
            # Query all predictions of current user
            query = select(Prediction).join(Screenshot).where(
                Screenshot.user_id == current_user.id
            )
            result = await db.execute(query)
            preds_to_delete = result.scalars().all()
        else:
            if not body.ids:
                return {"success": True, "message": "No logs selected."}
            # Query specified IDs
            query = select(Prediction).join(Screenshot).where(
                Prediction.id.in_(body.ids),
                Screenshot.user_id == current_user.id
            )
            result = await db.execute(query)
            preds_to_delete = result.scalars().all()
            
        deleted_count = len(preds_to_delete)
        for pred in preds_to_delete:
            await db.delete(pred)
            
        await db.commit()
        
        return {
            "success": True,
            "message": f"Successfully deleted {deleted_count} prediction records."
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to bulk delete predictions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while bulk deleting predictions."
        )
