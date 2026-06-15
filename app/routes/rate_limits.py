import logging
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.rate_limit import RateLimit
from backend.app.models.log import Log
from backend.app.services.security import get_current_user

logger = logging.getLogger("RateLimitRoutes")
router = APIRouter()

# Default limits configuration (can also be loaded from environment variables)
MAX_PER_MINUTE = 5
MAX_PER_HOUR = 60
MAX_PER_DAY = 200

@router.get("/")
async def get_rate_limit_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Retrieves usage statistics and configuration parameters for AI request rate limits."""
    try:
        # Load user rate limit records from DB
        cursor = db.rate_limits.find({"user_id": current_user.id})
        rows_docs = await cursor.to_list(length=100)
        rows = [RateLimit.from_dict(r) for r in rows_docs]
        
        # Structure usage counts
        now = datetime.now(timezone.utc)
        current_minute_window = now.strftime("%Y-%m-%d %H:%M")
        current_hour_window = now.strftime("%Y-%m-%d %H")
        current_day_window = now.strftime("%Y-%m-%d")
        
        usage = {
            "minute": 0,
            "hour": 0,
            "day": 0
        }
        
        for row in rows:
            if row.time_window == f"{current_minute_window}_min":
                usage["minute"] = row.request_count
            elif row.time_window == f"{current_hour_window}_hour":
                usage["hour"] = row.request_count
            elif row.time_window == f"{current_day_window}_day":
                usage["day"] = row.request_count
                
        # Fetch blocked request history
        log_filter = {"event_type": "RATE_LIMIT_BLOCKED"}
        # If not admin, filter by user
        if current_user.role != "admin":
            log_filter["user_id"] = current_user.id
            
        logs_cursor = db.logs.find(log_filter).sort("timestamp", -1).limit(10)
        blocked_docs = await logs_cursor.to_list(length=10)
        blocked_logs = [Log.from_dict(r) for r in blocked_docs]
        
        return {
            "success": True,
            "limits": {
                "max_per_minute": MAX_PER_MINUTE,
                "max_per_hour": MAX_PER_HOUR,
                "max_per_day": MAX_PER_DAY
            },
            "usage": usage,
            "blocked_requests": [r.to_dict() for r in blocked_logs]
        }
    except Exception as e:
        logger.error(f"Failed to fetch rate limit stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve rate limit metrics."
        )
