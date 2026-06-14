import logging
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

logger = logging.getLogger("TimeHelper")
logger.setLevel(logging.INFO)

def check_monitoring_hours() -> tuple[bool, str, str]:
    """
    Checks if the current time is within the allowed window of 09:15 AM to 03:15 PM
    in the configured timezone.
    Returns:
        (is_within_hours, formatted_current_time, timezone_name)
    """
    tz_name = os.getenv("MONITORING_TIMEZONE", "Asia/Kolkata")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning(f"Timezone '{tz_name}' invalid. Falling back to UTC.")
        tz_name = "UTC"
        tz = ZoneInfo("UTC")
        
    now = datetime.now(tz)
    current_time = now.time()
    
    # Check if weekday (Monday=0 to Friday=4)
    is_weekday = now.weekday() < 5
    
    start_time = time(9, 15)
    end_time = time(15, 15)
    
    is_valid = is_weekday and (start_time <= current_time <= end_time)
    return is_valid, now.strftime("%Y-%m-%d %I:%M:%S %p"), tz_name

