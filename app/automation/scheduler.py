import logging
import asyncio
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

async def execute_analysis_cycle(session: AsyncSession, stock_symbol: str = "NIFTY50") -> StockPrediction:
    """
    Core pipeline executor that orchestrates browser capture, OpenAI Vision analysis,
    database writing, and WebSocket broadcasting.
    
    Can be run both by background scheduler and immediate manual endpoint triggers.
    """
    logger.info("⚡ Executing core chart analysis pipeline cycle...")
    
    # 1. Capture dynamic chart screenshot using Playwright
    capture_result = await browser.capture_chart()
    
    # 2. Feed image to OpenAI Vision API (or dynamic offline simulation)
    ai_analysis = await ai.analyze_chart(capture_result["absolute_path"])
    
    # 3. Create the database record
    prediction = StockPrediction(
        stock_symbol=stock_symbol,
        image_path=capture_result["filename"],
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
    """Starts the cron automation background engine."""
    logger.info("⏰ Initializing APScheduler Background Engine (Interval: 5 minutes)...")
    
    # Setup cron every 5 minutes (equivalent to node-cron '*/5 * * * *')
    scheduler.add_job(run_pipeline_cycle, 'cron', minute='*/5', id='chart_pipeline_job')
    scheduler.start()
    
    # Schedule a one-time bootstrap cycle after 5 seconds to guarantee immediate data for the frontend
    async def delayed_bootstrap():
        await asyncio.sleep(5)
        logger.info("⚡ Executing initial server boot validation capture...")
        await run_pipeline_cycle()
        
    asyncio.create_task(delayed_bootstrap())
