import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

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
    db: AsyncSession = Depends(get_db)
):
    """Retrieves usage statistics and configuration parameters for AI request rate limits."""
    try:
        # Load user rate limit records from DB
        limit_query = select(RateLimit).where(RateLimit.user_id == current_user.id)
        limit_result = await db.execute(limit_query)
        rows = limit_result.scalars().all()
        
        # Structure usage counts
        now = datetime.utcnow()
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
        log_query = select(Log).where(
            Log.event_type == "RATE_LIMIT_BLOCKED"
        )
        # If not admin, filter by user
        if current_user.role != "admin":
            log_query = log_query.where(Log.user_id == current_user.id)
            
        log_query = log_query.order_by(Log.timestamp.desc()).limit(10)
        log_result = await db.execute(log_query)
        blocked_logs = log_result.scalars().all()
        
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
