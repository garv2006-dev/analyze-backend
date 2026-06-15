import logging
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone

from backend.app.database import get_db, get_next_sequence
from backend.app.models.user import User
from backend.app.models.target_url import TargetURL
from backend.app.models.log import Log
from backend.app.services.security import get_current_user
from backend.app.services.time_helper import check_monitoring_hours
from backend.app import config

logger = logging.getLogger("MonitoringRoutes")
logger.setLevel(logging.INFO)

router = APIRouter()

class StatusUpdateRequest(BaseModel):
    status: str # "active", "inactive"

@router.get("/status")
async def get_monitoring_status(current_user: User = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Retrieves the active monitoring status for the user's target URL."""
    target_doc = await db.target_urls.find_one({"user_id": current_user.id})
    target = TargetURL.from_dict(target_doc)
    
    if not target:
        return {
            "success": True,
            "status": "inactive",
            "has_url": False
        }
        
    is_valid, current_time_str, tz_name = check_monitoring_hours()
    
    return {
        "success": True,
        "status": target.status,
        "has_url": True,
        "url": target.url,
        "is_within_hours": is_valid,
        "server_time": current_time_str,
        "timezone": tz_name
    }

@router.post("/status")
async def update_monitoring_status(
    body: StatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Starts or stops monitoring. Validates working hours if attempting to activate."""
    new_status = body.status.strip().lower()
    if new_status not in ["active", "inactive"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be either 'active' or 'inactive'."
        )
        
    target_doc = await db.target_urls.find_one({"user_id": current_user.id})
    target = TargetURL.from_dict(target_doc)
    
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No target URL configured. Please configure a target URL first."
        )
        
    # Check working hours if activating
    if new_status == "active":
        is_valid, current_time_str, tz_name = check_monitoring_hours()
        if not is_valid:
            # Audit log the attempt
            audit_id = await get_next_sequence("logs")
            await db.logs.insert_one({
                "id": audit_id,
                "user_id": current_user.id,
                "event_type": "MONITORING_START_BLOCKED",
                "message": f"Attempted to start monitoring outside allowed hours ({current_time_str} {tz_name}).",
                "timestamp": datetime.now(timezone.utc)
            })
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Monitoring can only be started during working hours (09:15 AM - 03:15 PM, Monday to Friday {tz_name}). Current server time: {current_time_str}."
            )
            
    # Update status
    now = datetime.now(timezone.utc)
    await db.target_urls.update_one(
        {"id": target.id},
        {"$set": {"status": new_status, "updated_at": now}}
    )
    
    # Audit log
    event = "MONITORING_START" if new_status == "active" else "MONITORING_STOP"
    message = f"User started monitoring for URL '{target.url}'." if new_status == "active" else f"User stopped monitoring for URL '{target.url}'."
    
    audit_id = await get_next_sequence("logs")
    await db.logs.insert_one({
        "id": audit_id,
        "user_id": current_user.id,
        "event_type": event,
        "message": message,
        "timestamp": now
    })
    
    return {
        "success": True,
        "status": new_status,
        "message": f"Monitoring successfully {new_status}."
    }
