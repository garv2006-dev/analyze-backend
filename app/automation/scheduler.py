import logging
import asyncio
from pathlib import Path
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app import config
from backend.app import database
from backend.app.models.user import User
from backend.app.models.target_url import TargetURL
from backend.app.models.screenshot import Screenshot
from backend.app.models.prediction import Prediction
from backend.app.models.log import Log
from backend.app.services import browser, ai
from backend.app.services.change_detector import detect_and_highlight_changes
from backend.app.services.rate_limiter import check_and_increment_rate_limit
from backend.app.services.websocket import ws_manager
from backend.app.services.time_helper import check_monitoring_hours

logger = logging.getLogger("Scheduler")
logger.setLevel(logging.INFO)

scheduler = AsyncIOScheduler()

async def execute_user_monitoring_cycle(db: AsyncSession, target: TargetURL):
    """
    Orchestrates the screenshot capture, change detection, and AI analysis cycle
    for a single target URL. Enforces rate limits and logs audit details.
    """
    user_id = target.user_id
    url_id = target.id
    target_url = target.url
    
    # 1. Enforce rate limiting
    allowed, limit_msg = await check_and_increment_rate_limit(db, user_id)
    if not allowed:
        # Rate limit hit: log block and return
        logger.warning(f"Skipping capture for user {user_id} due to rate limits: {limit_msg}")
        return
        
    logger.info(f"⚡ Running monitoring scan for User {user_id} on URL: {target_url}")
    
    try:
        # 2. Capture screenshot using Playwright browser service
        capture_log = Log(
            user_id=user_id,
            event_type="SCREENSHOT_CAPTURE",
            message=f"Capturing screenshot of URL '{target_url}'..."
        )
        db.add(capture_log)
        await db.commit()
        
        capture_result = await browser.capture_chart(target_url=target_url, stock_symbol="TARGET")
        
        # 3. Detect visual changes if there was a previous screenshot
        prev_query = select(Screenshot).where(
            Screenshot.url_id == url_id
        ).order_by(Screenshot.timestamp.desc()).limit(1)
        prev_res = await db.execute(prev_query)
        prev_screenshot = prev_res.scalars().first()
        
        highlighted_image_path = None
        if prev_screenshot:
            prev_abs_path = str(config.SCREENSHOTS_DIR / prev_screenshot.image_path)
            highlight_filename = f"highlighted_{capture_result['filename']}"
            
            highlighted_image_path = detect_and_highlight_changes(
                prev_path=prev_abs_path,
                curr_path=capture_result["absolute_path"],
                output_filename=highlight_filename
            )
            
        # 4. Save screenshot details
        new_screenshot = Screenshot(
            user_id=user_id,
            url_id=url_id,
            image_path=capture_result["filename"],
            highlighted_image_path=highlighted_image_path
        )
        db.add(new_screenshot)
        await db.flush() # Generate ID
        
        # 5. Call AI reasoning (or simulation fallback) on screenshot
        ai_log = Log(
            user_id=user_id,
            event_type="AI_PREDICTION",
            message="Analyzing screenshot for visual patterns and change predictions..."
        )
        db.add(ai_log)
        await db.commit()
        
        ai_analysis = await ai.analyze_chart(capture_result["absolute_path"], extracted_price=None)
        
        # Merge prediction JSON values
        ai_result_payload = {
            "trend_direction": ai_analysis["trend_direction"],
            "confidence_score": ai_analysis["confidence_score"],
            "support_levels": ai_analysis["support_levels"],
            "resistance_levels": ai_analysis["resistance_levels"],
            "ai_summary": ai_analysis["ai_summary"],
            **ai_analysis.get("prediction_json", {})
        }
        
        new_prediction = Prediction(
            screenshot_id=new_screenshot.id,
            ai_result=ai_result_payload,
            confidence_score=ai_analysis["confidence_score"]
        )
        db.add(new_prediction)
        
        # Save audit success log
        success_log = Log(
            user_id=user_id,
            event_type="MONITORING_CYCLE_SUCCESS",
            message=f"Successfully captured and analyzed '{target_url}'. Changes Highlighted: {bool(highlighted_image_path)}."
        )
        db.add(success_log)
        await db.commit()
        
        # 6. Broadcast updates via WebSocket
        prediction_dict = new_prediction.to_dict(
            screenshot_path=new_screenshot.image_path,
            highlighted_path=new_screenshot.highlighted_image_path
        )
        await ws_manager.broadcast({
            "success": True,
            "type": "NEW_PREDICTION",
            "user_id": user_id,
            "data": prediction_dict
        })
        
        logger.info(f"✔️ Successfully completed monitoring cycle for user {user_id}.")
        return new_prediction
        
    except Exception as e:
        logger.error(f"Error in execution cycle for User {user_id}: {e}")
        fail_log = Log(
            user_id=user_id,
            event_type="MONITORING_CYCLE_FAILED",
            message=f"Failed capture/AI analysis cycle: {str(e)}"
        )
        db.add(fail_log)
        await db.commit()

async def run_pipeline_cycle():
    """
    Triggered by the APScheduler background daemon every 1 minute.
    Runs screenshot capture and AI checks for all users with active target URLs,
    provided it is within the working hours window (09:15 AM - 03:15 PM).
    """
    # 1. Enforce schedule control working hours
    is_within_hours, current_time_str, tz_name = check_monitoring_hours()
    if not is_within_hours:
        logger.info(f"⏸️ Scheduler check bypassed: outside working hours (current time is {current_time_str} {tz_name}).")
        return
        
    logger.info("⏰ [SCHEDULER] Scanning for active target URLs...")
    
    # 2. Query all active target URLs
    active_targets = []
    try:
        async with database.SessionLocal() as db:
            result = await db.execute(select(TargetURL).where(TargetURL.status == "active"))
            active_targets = result.scalars().all()
    except Exception as e:
        logger.error(f"Failed to load active target URLs for scheduler: {e}")
        return
        
    if not active_targets:
        logger.info("No active target URLs currently configured for monitoring.")
        return
        
    logger.info(f"⏰ [SCHEDULER] Found {len(active_targets)} active URL(s) to process.")
    
    # Run capture cycle for each target URL asynchronously
    for target in active_targets:
        async with database.SessionLocal() as session:
            try:
                # Retrieve fresh row from session
                res = await session.execute(select(TargetURL).where(TargetURL.id == target.id))
                fresh_target = res.scalars().first()
                if fresh_target and fresh_target.status == "active":
                    await execute_user_monitoring_cycle(session, fresh_target)
            except Exception as loop_err:
                logger.error(f"Error executing task for Target ID {target.id}: {loop_err}")

def start_scheduler():
    """Starts the background scheduler running the monitoring check every 1 minute."""
    logger.info("⏰ Initializing APScheduler Background Engine (Interval: 1 minute)...")
    
    # Schedule interval check every 1 minute
    scheduler.add_job(run_pipeline_cycle, 'interval', minutes=1, id='chart_pipeline_job')
    scheduler.start()
    
    # We do NOT run bootstrap cycle here because that could run outside working hours
    # or before database tables are created. We will let the scheduler check naturally.
