import logging
import asyncio
import json
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app import config
from backend.app import database
from backend.app.models.prediction import StockPrediction
from backend.app.services import browser, ai
from backend.app.services.websocket import ws_manager

logger = logging.getLogger("Scheduler")
logger.setLevel(logging.INFO)

scheduler = AsyncIOScheduler()
SETTINGS_FILE = Path(__file__).resolve().parent.parent / "scheduler_settings.json"

def get_saved_interval() -> int:
    """Helper to load persistent interval configuration from disk or default to 5 minutes."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                return int(data.get("interval_minutes", 5))
        except Exception as e:
            logger.warning(f"Could not load saved interval settings: {e}")
    return 5

def save_interval(minutes: int):
    """Helper to persist interval configuration to disk."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"interval_minutes": minutes}, f)
    except Exception as e:
        logger.error(f"Failed to persist scheduler settings: {e}")

def update_scheduler_interval(minutes: int) -> bool:
    """Reschedules the active background chart analysis job dynamically and persists settings."""
    save_interval(minutes)
    try:
        scheduler.reschedule_job('chart_pipeline_job', trigger='interval', minutes=minutes)
        logger.info(f"✔️ Scheduler successfully rescheduled to run every {minutes} minutes.")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to reschedule job dynamically: {e}")
        return False

async def execute_analysis_cycle(session: AsyncSession, stock_symbol: str = "NIFTY50", target_url: str = None) -> StockPrediction:
    """
    Core pipeline executor that orchestrates browser capture, OpenAI Vision analysis,
    database writing, and WebSocket broadcasting.
    
    Can be run both by background scheduler and immediate manual endpoint triggers.
    """
    logger.info("⚡ Executing core chart analysis pipeline cycle...")
    
    # 1. Capture dynamic chart screenshot using Playwright
    capture_result = await browser.capture_chart(target_url=target_url)

    
    try:
        # 2. Feed image to OpenAI Vision API (or dynamic offline simulation)
        ai_analysis = await ai.analyze_chart(capture_result["absolute_path"])
        
        # 2.5. Upload image to Cloudinary if enabled
        image_path_to_save = capture_result["filename"]
        if config.IS_CLOUDINARY_ENABLED:
            try:
                logger.info("☁️ Cloudinary is enabled. Uploading screenshot...")
                from backend.app.services import cloudinary as cloudinary_service
                cloudinary_url = await asyncio.to_thread(
                    cloudinary_service.upload_image, 
                    capture_result["absolute_path"]
                )
                if cloudinary_url:
                    image_path_to_save = cloudinary_url
            except Exception as upload_err:
                logger.error(f"⚠️ Failed to upload screenshot to Cloudinary, using local fallback: {upload_err}")
        
        # 3. Create the database record
        prediction = StockPrediction(
            stock_symbol=stock_symbol,
            image_path=image_path_to_save,
            trend_direction=ai_analysis["trend_direction"],
            confidence_score=ai_analysis["confidence_score"],
            support_levels=ai_analysis["support_levels"],
            resistance_levels=ai_analysis["resistance_levels"],
            prediction_json=ai_analysis["prediction_json"],
            ai_summary=ai_analysis["ai_summary"]
        )
        
        session.add(prediction)
        # Save transaction
        await session.flush()
        await session.refresh(prediction)
        
        logger.info(f"💾 Prediction persisted successfully with ID #{prediction.id}")
        
        # 4. Broadcast the newly created prediction over all active WebSockets
        prediction_dict = prediction.to_dict()
        await ws_manager.broadcast({
            "success": True,
            "type": "NEW_PREDICTION",
            "data": prediction_dict
        })
        
        return prediction
        
    finally:
        # Always clean up the temporary local screenshot to avoid storing images in the codebase folder
        try:
            from pathlib import Path
            local_file = Path(capture_result["absolute_path"])
            if local_file.exists():
                local_file.unlink()
                logger.info(f"🗑️ Cleaned up temporary local screenshot file: {local_file.name}")
        except Exception as cleanup_err:
            logger.warning(f"⚠️ Failed to delete temporary local screenshot: {cleanup_err}")

async def run_pipeline_cycle():
    """Triggered by the APScheduler background daemon."""
    logger.info("⏰ [CRON ENGINE] Triggering background chart capture & analysis cycle...")
    
    async with database.SessionLocal() as session:
        try:
            prediction = await execute_analysis_cycle(session)
            await session.commit()
            logger.info(f"✔️ [CRON ENGINE] Background automated cycle successful. ID: #{prediction.id}\n")
        except Exception as error:
            await session.rollback()
            logger.error(f"❌ [CRON ENGINE] Background analysis sequence failed: {error}")

def start_scheduler():
    """Starts the cron automation background engine using a dynamic, user-configured interval."""
    interval = get_saved_interval()
    logger.info(f"⏰ Initializing APScheduler Background Engine (Interval: {interval} minutes)...")
    
    # Setup interval trigger
    scheduler.add_job(run_pipeline_cycle, 'interval', minutes=interval, id='chart_pipeline_job')
    scheduler.start()
    
    # Schedule a one-time bootstrap cycle after 5 seconds to guarantee immediate data for the frontend
    async def delayed_bootstrap():
        await asyncio.sleep(5)
        logger.info("⚡ Executing initial server boot validation capture...")
        await run_pipeline_cycle()
        
    asyncio.create_task(delayed_bootstrap())
