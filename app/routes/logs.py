import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

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
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Fetches paginated event logs, supporting event type filters and text search queries."""
    try:
        # Build MongoDB query filter
        query_filter = {}
        
        # If user is admin, they can see all logs. Otherwise, they can only see their own logs.
        if current_user.role != "admin":
            query_filter["user_id"] = current_user.id
            
        if event_type and event_type.upper() != "ALL":
            query_filter["event_type"] = event_type.upper()
            
        if search:
            query_filter["message"] = {"$regex": re_escape(search), "$options": "i"}
            
        # Count total documents matching query
        total = await db.logs.count_documents(query_filter)
        
        # Paginate and order by timestamp descending
        offset = (page - 1) * page_size
        cursor = db.logs.find(query_filter).sort("timestamp", -1).skip(offset).limit(page_size)
        rows_docs = await cursor.to_list(length=page_size)
        
        rows = [Log.from_dict(r) for r in rows_docs]
        
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

def re_escape(text: str) -> str:
    """Escapes special regex characters in search string."""
    import re
    return re.escape(text)
