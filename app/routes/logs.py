import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.log import Log
from backend.app.services.security import get_current_user

logger = logging.getLogger("LogRoutes")
router = APIRouter()

@router.get("/")
async def get_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    event_type: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Fetches paginated event logs, supporting event type filters and text search queries."""
    try:
        # Build query
        query = select(Log)
        
        # If user is admin, they can see all logs. Otherwise, they can only see their own logs.
        if current_user.role != "admin":
            query = query.where(Log.user_id == current_user.id)
            
        if event_type and event_type.upper() != "ALL":
            query = query.where(Log.event_type == event_type.upper())
            
        if search:
            query = query.where(Log.message.ilike(f"%{search}%"))
            
        # Count query
        count_query = select(func.count()).select_from(query.subquery())
        count_res = await db.execute(count_query)
        total = count_res.scalar() or 0
        
        # Paginate and order descending
        offset = (page - 1) * page_size
        query = query.order_by(Log.timestamp.desc()).offset(offset).limit(page_size)
        
        result = await db.execute(query)
        rows = result.scalars().all()
        
        return {
            "success": True,
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": [r.to_dict() for r in rows]
        }
    except Exception as e:
        logger.error(f"Failed to fetch audit logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve monitoring logs from database."
        )
