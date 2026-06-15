import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone

from backend.app.database import get_db, get_next_sequence
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

from backend.app.models.saved_asset import SavedAsset

def clean_url(url: str) -> str:
    if not url:
        return ""
    url = url.split("?")[0]
    url = url.rstrip("/")
    url = url.replace("/ext/", "/")
    url = url.replace("https://", "").replace("http://", "")
    url = url.replace("www.groww.in", "").replace("groww.in", "")
    return url

@router.get("/")
async def get_predictions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Fetches a paginated list of predictions belonging to the authenticated User."""
    try:
        # Build aggregation pipeline to join Prediction -> Screenshot -> TargetURL
        pipeline = [
            {
                "$lookup": {
                    "from": "screenshots",
                    "localField": "screenshot_id",
                    "foreignField": "id",
                    "as": "screenshot"
                }
            },
            {"$unwind": "$screenshot"},
            {"$match": {"screenshot.user_id": current_user.id}},
            {
                "$lookup": {
                    "from": "target_urls",
                    "localField": "screenshot.url_id",
                    "foreignField": "id",
                    "as": "target_url"
                }
            },
            {"$unwind": "$target_url"}
        ]
        
        # Count total
        count_pipeline = pipeline + [{"$count": "total"}]
        count_res = await db.predictions.aggregate(count_pipeline).to_list(1)
        total = count_res[0]["total"] if count_res else 0
        
        # Paginate and order by newest first
        offset = (page - 1) * page_size
        data_pipeline = pipeline + [
            {"$sort": {"timestamp": -1}},
            {"$skip": offset},
            {"$limit": page_size}
        ]
        
        cursor = db.predictions.aggregate(data_pipeline)
        rows = await cursor.to_list(length=page_size)
        
        # Load saved assets to map URL -> symbol
        assets_cursor = db.saved_assets.find()
        assets_docs = await assets_cursor.to_list(length=None)
        assets = [SavedAsset.from_dict(d) for d in assets_docs]
        
        asset_map = {}
        for asset in assets:
            asset_map[clean_url(asset.url)] = asset.symbol
            
        data = []
        for row in rows:
            p = Prediction.from_dict(row)
            screenshot_data = row["screenshot"]
            target_url_data = row["target_url"]
            
            cleaned_target = clean_url(target_url_data.get("url"))
            symbol = asset_map.get(cleaned_target)
            if not symbol:
                parts = cleaned_target.split("/")
                symbol = parts[-1].replace("-", " ").upper() if parts else "TARGET"
                
            data.append(p.to_dict(
                screenshot_path=screenshot_data.get("image_path"), 
                highlighted_path=screenshot_data.get("highlighted_image_path"),
                stock_symbol=symbol
            ))
            
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
async def get_latest_prediction(current_user: User = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Retrieves the single latest prediction analysis for the current user."""
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "screenshots",
                    "localField": "screenshot_id",
                    "foreignField": "id",
                    "as": "screenshot"
                }
            },
            {"$unwind": "$screenshot"},
            {"$match": {"screenshot.user_id": current_user.id}},
            {
                "$lookup": {
                    "from": "target_urls",
                    "localField": "screenshot.url_id",
                    "foreignField": "id",
                    "as": "target_url"
                }
            },
            {"$unwind": "$target_url"},
            {"$sort": {"timestamp": -1}},
            {"$limit": 1}
        ]
        
        rows = await db.predictions.aggregate(pipeline).to_list(1)
        
        if not rows:
            return {
                "success": True,
                "data": None
            }
            
        row = rows[0]
        p = Prediction.from_dict(row)
        s = Screenshot.from_dict(row["screenshot"])
        t = TargetURL.from_dict(row["target_url"])
        
        # Resolve symbol
        assets_cursor = db.saved_assets.find()
        assets_docs = await assets_cursor.to_list(length=None)
        assets = [SavedAsset.from_dict(d) for d in assets_docs]
        
        cleaned_target = clean_url(t.url)
        symbol = "TARGET"
        for asset in assets:
            if clean_url(asset.url) == cleaned_target:
                symbol = asset.symbol
                break
        if symbol == "TARGET":
            parts = cleaned_target.split("/")
            symbol = parts[-1].replace("-", " ").upper() if parts else "TARGET"
            
        return {
            "success": True,
            "data": p.to_dict(
                screenshot_path=s.image_path, 
                highlighted_path=s.highlighted_image_path,
                stock_symbol=symbol
            )
        }
    except Exception as e:
        logger.error(f"Failed to retrieve latest prediction: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve latest prediction."
        )

@router.post("/trigger")
async def trigger_manual_analysis(current_user: User = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Manually triggers an immediate screenshot capture and AI prediction analysis cycle."""
    # 1. Fetch user's target URL
    url_doc = await db.target_urls.find_one({"user_id": current_user.id})
    target = TargetURL.from_dict(url_doc)
    
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No target URL configured. Please add a target URL first."
        )
        
    # 2. Check working hours constraint
    is_valid, current_time_str, tz_name = check_monitoring_hours()
    if not is_valid:
        # Log failure
        audit_id = await get_next_sequence("logs")
        await db.logs.insert_one({
            "id": audit_id,
            "user_id": current_user.id,
            "event_type": "MANUAL_TRIGGER_BLOCKED",
            "message": f"Attempted to trigger manual capture outside allowed hours ({current_time_str} {tz_name}).",
            "timestamp": datetime.now(timezone.utc)
        })
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Monitoring is only available between 09:15 AM and 03:15 PM, Monday to Friday {tz_name}. Current server time: {current_time_str}."
        )
        
    # 3. Execute monitoring cycle
    try:
        prediction = await execute_user_monitoring_cycle(db, target)
        
        # Load screenshot details for serialization
        screenshot_doc = await db.screenshots.find_one({"id": prediction.screenshot_id})
        screenshot = Screenshot.from_dict(screenshot_doc)
        
        # Resolve symbol
        assets_cursor = db.saved_assets.find()
        assets_docs = await assets_cursor.to_list(length=None)
        assets = [SavedAsset.from_dict(d) for d in assets_docs]
        
        cleaned_target = clean_url(target.url)
        symbol = "TARGET"
        for asset in assets:
            if clean_url(asset.url) == cleaned_target:
                symbol = asset.symbol
                break
        if symbol == "TARGET":
            parts = cleaned_target.split("/")
            symbol = parts[-1].replace("-", " ").upper() if parts else "TARGET"
            
        return {
            "success": True,
            "data": prediction.to_dict(
                screenshot_path=screenshot.image_path if screenshot else None,
                highlighted_path=screenshot.highlighted_image_path if screenshot else None,
                stock_symbol=symbol
            )
        }
    except Exception as e:
        logger.error(f"Manual scan cycle failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"On-demand browser capture/AI analysis cycle failed: {str(e)}"
        )

@router.delete("/{id}")
async def delete_prediction(id: int, current_user: User = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Deletes a single prediction record by ID if it belongs to the current user."""
    try:
        # Check prediction ownership via Screenshot join
        prediction_doc = await db.predictions.find_one({"id": id})
        if not prediction_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prediction record with ID #{id} was not found."
            )
            
        screenshot_doc = await db.screenshots.find_one({"id": prediction_doc.get("screenshot_id")})
        if not screenshot_doc or screenshot_doc.get("user_id") != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prediction record with ID #{id} was not found."
            )
            
        await db.predictions.delete_one({"id": id})
        
        return {
            "success": True,
            "message": f"Prediction record #{id} has been deleted."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete prediction record #{id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the prediction record."
        )

@router.post("/bulk-delete")
async def bulk_delete_predictions(body: BulkDeleteRequest, current_user: User = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Bulk deletes selected or all predictions for the current user."""
    try:
        # Get user's screenshot IDs
        screenshot_cursor = db.screenshots.find({"user_id": current_user.id}, {"id": 1})
        screenshot_docs = await screenshot_cursor.to_list(length=None)
        user_screenshot_ids = [s.get("id") for s in screenshot_docs]
        
        if body.delete_all:
            result = await db.predictions.delete_many({
                "screenshot_id": {"$in": user_screenshot_ids}
            })
            deleted_count = result.deleted_count
        else:
            if not body.ids:
                return {"success": True, "message": "No logs selected."}
            
            result = await db.predictions.delete_many({
                "id": {"$in": body.ids},
                "screenshot_id": {"$in": user_screenshot_ids}
            })
            deleted_count = result.deleted_count
            
        return {
            "success": True,
            "message": f"Successfully deleted {deleted_count} prediction records."
        }
    except Exception as e:
        logger.error(f"Failed to bulk delete predictions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while bulk deleting predictions."
        )
