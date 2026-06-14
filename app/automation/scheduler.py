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
            prev_abs_path = None
            if prev_screenshot.image_path.startswith("http://") or prev_screenshot.image_path.startswith("https://"):
                filename_only = prev_screenshot.image_path.split("/")[-1]
                local_path = config.SCREENSHOTS_DIR / filename_only
                if local_path.exists():
                    prev_abs_path = str(local_path)
            else:
                local_path = config.SCREENSHOTS_DIR / prev_screenshot.image_path
                if local_path.exists():
                    prev_abs_path = str(local_path)
                    
            if prev_abs_path:
                highlight_filename = f"highlighted_{capture_result['filename']}"
                highlighted_image_path = detect_and_highlight_changes(
                    prev_path=prev_abs_path,
                    curr_path=capture_result["absolute_path"],
                    output_filename=highlight_filename
                )
            
        # 3.5. Upload images to Cloudinary if enabled
        saved_image_path = capture_result["filename"]
        if config.IS_CLOUDINARY_ENABLED:
            from backend.app.services.cloudinary import upload_image
            try:
                cloudinary_url = await asyncio.to_thread(
                    upload_image,
                    capture_result["absolute_path"],
                    f"graph_{int(datetime.now().timestamp())}"
                )
                if cloudinary_url:
                    saved_image_path = cloudinary_url
            except Exception as upload_err:
                logger.error(f"Failed to upload standard screenshot to Cloudinary: {upload_err}")
                
        saved_highlighted_path = highlighted_image_path
        if highlighted_image_path and config.IS_CLOUDINARY_ENABLED:
            from backend.app.services.cloudinary import upload_image
            try:
                highlighted_abs_path = str(config.SCREENSHOTS_DIR / highlighted_image_path)
                cloudinary_url = await asyncio.to_thread(
                    upload_image,
                    highlighted_abs_path,
                    f"highlighted_{int(datetime.now().timestamp())}"
                )
                if cloudinary_url:
                    saved_highlighted_path = cloudinary_url
            except Exception as upload_err:
                logger.error(f"Failed to upload highlighted screenshot to Cloudinary: {upload_err}")

        # 4. Save screenshot details
        new_screenshot = Screenshot(
            user_id=user_id,
            url_id=url_id,
            image_path=saved_image_path,
            highlighted_image_path=saved_highlighted_path
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
        
        ai_analysis = await ai.analyze_chart(capture_result["absolute_path"], extracted_price=None, target_url=target_url)
        
        # Check if the chart is a valid stock market chart
        if not ai_analysis.get("is_stock_market_chart", True):
            # Clean up the invalid screenshot file
            try:
                Path(capture_result["absolute_path"]).unlink(missing_ok=True)
            except Exception:
                pass
            raise ValueError("The captured image does not represent a valid stock market chart. Only stock market charts are allowed.")
            
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
        def clean_url_local(url: str) -> str:
            if not url:
                return ""
            url = url.split("?")[0]
            url = url.rstrip("/")
            url = url.replace("/ext/", "/")
            url = url.replace("https://", "").replace("http://", "")
            url = url.replace("www.groww.in", "").replace("groww.in", "")
            return url
            
        from backend.app.models.saved_asset import SavedAsset
        assets_res = await db.execute(select(SavedAsset))
        assets = assets_res.scalars().all()
        cleaned_target = clean_url_local(target.url)
        symbol = "TARGET"
        for asset in assets:
            if clean_url_local(asset.url) == cleaned_target:
                symbol = asset.symbol
                break
        if symbol == "TARGET":
            parts = cleaned_target.split("/")
            symbol = parts[-1].replace("-", " ").upper() if parts else "TARGET"

        prediction_dict = new_prediction.to_dict(
            screenshot_path=new_screenshot.image_path,
            highlighted_path=new_screenshot.highlighted_image_path,
            stock_symbol=symbol
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
        await db.rollback()
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
                    # Check if enough time has elapsed since the last screenshot of this target
                    prev_query = select(Screenshot).where(
                        Screenshot.url_id == fresh_target.id
                    ).order_by(Screenshot.timestamp.desc()).limit(1)
                    prev_res = await session.execute(prev_query)
                    last_screenshot = prev_res.scalars().first()
                    
                    if last_screenshot:
                        from datetime import datetime, timezone
                        ts = last_screenshot.timestamp
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        
                        now = datetime.now(timezone.utc)
                        elapsed_seconds = (now - ts).total_seconds()
                        elapsed_minutes = elapsed_seconds / 60.0
                        
                        # Use a small safety margin (e.g. 5 seconds) to avoid timing jitter issues
                        safety_margin_minutes = 5.0 / 60.0
                        if (elapsed_minutes + safety_margin_minutes) < fresh_target.interval_minutes:
                            logger.info(
                                f"⏸️ [SCHEDULER] Skipping target {fresh_target.id} ({fresh_target.url}): "
                                f"only {elapsed_minutes:.2f} mins elapsed since last capture (interval: {fresh_target.interval_minutes} mins)."
                            )
                            continue
                    
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
