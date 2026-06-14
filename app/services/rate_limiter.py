import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.models.rate_limit import RateLimit
from backend.app.models.log import Log

logger = logging.getLogger("RateLimiter")
logger.setLevel(logging.INFO)

# Default Limits Configuration
MAX_PER_MINUTE = 5
MAX_PER_HOUR = 60
MAX_PER_DAY = 200

async def check_and_increment_rate_limit(db: AsyncSession, user_id: int) -> tuple[bool, str]:
    """
    Checks if a user is within their configured AI request rate limits.
    If they are, increments request counts for minute, hour, and day windows.
    Returns:
        (is_allowed, error_message)
    """
    now = datetime.now(timezone.utc)
    current_minute_window = now.strftime("%Y-%m-%d %H:%M")
    current_hour_window = now.strftime("%Y-%m-%d %H")
    current_day_window = now.strftime("%Y-%m-%d")
    
    windows = [
        {"key": f"{current_minute_window}_min", "limit": MAX_PER_MINUTE, "name": "minute"},
        {"key": f"{current_hour_window}_hour", "limit": MAX_PER_HOUR, "name": "hour"},
        {"key": f"{current_day_window}_day", "limit": MAX_PER_DAY, "name": "day"}
    ]
    
    limit_records = {}
    
    for win in windows:
        # Check database for existing counter in this window
        query = select(RateLimit).where(
            RateLimit.user_id == user_id,
            RateLimit.time_window == win["key"]
        )
        res = await db.execute(query)
        record = res.scalars().first()
        
        if record:
            if record.request_count >= win["limit"]:
                # Limit exceeded! Log and block.
                msg = f"API request blocked. Exceeded {win['name']} rate limit of {win['limit']} requests."
                logger.warning(f"Rate limit hit for user {user_id} in window {win['key']}: {msg}")
                
                blocked_log = Log(
                    user_id=user_id,
                    event_type="RATE_LIMIT_BLOCKED",
                    message=msg
                )
                db.add(blocked_log)
                await db.commit()
                return False, msg
            limit_records[win["key"]] = record
        else:
            limit_records[win["key"]] = None
            
    # All windows are valid: perform incrementations
    for win in windows:
        record = limit_records[win["key"]]
        if record:
            record.request_count += 1
        else:
            new_record = RateLimit(
                user_id=user_id,
                time_window=win["key"],
                request_count=1
            )
            db.add(new_record)
            
    await db.commit()
    return True, ""
