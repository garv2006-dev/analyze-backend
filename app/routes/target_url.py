import logging
import re
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.target_url import TargetURL
from backend.app.models.log import Log
from backend.app.services.security import get_current_user

logger = logging.getLogger("TargetURLRoutes")
logger.setLevel(logging.INFO)

router = APIRouter()

class TargetURLRequest(BaseModel):
    url: str = Field(..., max_length=1024)

def validate_url(url: str) -> bool:
    """Validates that a URL string is formatted correctly and begins with http:// or https://."""
    url_regex = r"^https?:\/\/[^\s\/$.?#].[^\s]*$"
    return bool(re.match(url_regex, url))

@router.get("/")
async def get_target_url(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Fetches the current user's target URL, returning null if none is configured."""
    result = await db.execute(select(TargetURL).where(TargetURL.user_id == current_user.id))
    target = result.scalars().first()
    return {
        "success": True,
        "data": target.to_dict() if target else None
    }

@router.post("/")
async def create_target_url(body: TargetURLRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Configures a target URL for the user, enforcing the single active URL restriction and validating the URL."""
    url = body.url.strip()
    
    # 1. Validate URL format
    if not validate_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL format. URL must start with http:// or https:// and be a valid web address."
        )
        
    # 2. Check if the user already has a configured URL
    existing_result = await db.execute(select(TargetURL).where(TargetURL.user_id == current_user.id))
    existing = existing_result.scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can configure only one target URL. Delete the existing one first to update."
        )
        
    # 3. Create and save the new target URL
    try:
        new_target = TargetURL(
            user_id=current_user.id,
            url=url,
            status="inactive" # Start as inactive; user must click "Start Monitoring" to enable it
        )
        db.add(new_target)
        await db.commit()
        await db.refresh(new_target)
        
        # Log successful audit event
        audit_log = Log(
            user_id=current_user.id,
            event_type="URL_CREATE",
            message=f"Configured target URL: '{url}'"
        )
        db.add(audit_log)
        await db.commit()
        
        return {
            "success": True,
            "data": new_target.to_dict()
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create target URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save target URL: {str(e)}"
        )

@router.delete("/")
async def delete_target_url(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Deletes the user's active target URL, resetting their monitoring session."""
    try:
        # Find the existing target URL
        result = await db.execute(select(TargetURL).where(TargetURL.user_id == current_user.id))
        target = result.scalars().first()
        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No target URL found to delete."
            )
            
        url_deleted = target.url
        await db.delete(target)
        
        # Log audit log
        audit_log = Log(
            user_id=current_user.id,
            event_type="URL_DELETE",
            message=f"Deleted target URL: '{url_deleted}'"
        )
        db.add(audit_log)
        await db.commit()
        
        return {
            "success": True,
            "message": f"Successfully deleted target URL '{url_deleted}'."
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete target URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete target URL."
        )
