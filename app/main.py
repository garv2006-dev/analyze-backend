import sys
sys.dont_write_bytecode = True
import asyncio

# Fix Windows event loop policy for Playwright subprocess compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import logging
import psutil
import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app import config
from backend.app import database
from backend.app.database import get_db, Base
from backend.app.services.websocket import ws_manager
from backend.app.automation.scheduler import start_scheduler, scheduler

# Import all routers
from backend.app.routes.predictions import router as predictions_router
from backend.app.routes.chat import router as chat_router
from backend.app.routes.auth import router as auth_router
from backend.app.routes.target_url import router as target_url_router
from backend.app.routes.monitoring import router as monitoring_router
from backend.app.routes.logs import router as logs_router
from backend.app.routes.rate_limits import router as rate_limits_router

# Import all models to ensure they are registered in SQLAlchemy metadata
from backend.app.models.user import User  # noqa: F401
from backend.app.models.target_url import TargetURL  # noqa: F401
from backend.app.models.screenshot import Screenshot  # noqa: F401
from backend.app.models.prediction import Prediction  # noqa: F401
from backend.app.models.log import Log  # noqa: F401
from backend.app.models.rate_limit import RateLimit  # noqa: F401

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Main")

# Keep track of server boot time
server_boot_time = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown lifecycle operations including database and cron initialization."""
    logger.info("⚡ Server is booting up...")
    
    # 1. Initialize active database connection (Postgres or SQLite fallback)
    await database.init_database()
    
    # 2. Dynamically create all schema tables on startup
    logger.info("⚙️ Ensuring all relational database tables exist...")
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✔️ Database tables verified.")
    
    # 2b. Safe Column Migration: Ensure 'interval_minutes' column exists on 'target_urls'
    logger.info("⚙️ Checking target_urls table schema for interval_minutes column...")
    async with database.engine.begin() as conn:
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE target_urls ADD COLUMN interval_minutes INTEGER DEFAULT 5 NOT NULL"))
            logger.info("✔️ Added missing 'interval_minutes' column to 'target_urls' table.")
        except Exception as migration_err:
            logger.info(f"ℹ️ Migration skipped (column 'interval_minutes' likely already exists): {migration_err}")
    
    # 3. Start the APScheduler automated pipeline engine
    start_scheduler()
    
    yield
    
    # Clean shutdown of scheduler
    logger.info("🔒 Server is shutting down. Tearing down APScheduler daemon...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("🔒 Shutdown completed.")

app = FastAPI(
    title="Aether Analytics — AI Graph Analysis Platform",
    description="Asynchronous Python FastAPI website monitoring pipeline.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS protection across origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow development clients
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(target_url_router, prefix="/api/target-url", tags=["Target URL"])
app.include_router(monitoring_router, prefix="/api/monitoring", tags=["Monitoring Control"])
app.include_router(predictions_router, prefix="/api/predictions", tags=["Predictions"])
app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
app.include_router(logs_router, prefix="/api/logs", tags=["Logs"])
app.include_router(rate_limits_router, prefix="/api/rate-limit-stats", tags=["Rate Limits"])

# Serve local screenshot files statically for dashboard fallback
app.mount("/screenshots", StaticFiles(directory=str(config.SCREENSHOTS_DIR)), name="screenshots")

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket connection socket for streaming instant real-time broadcasts."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # We keep the connection alive by listening for ping/pong signals
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket encounter disruption: {e}")
        ws_manager.disconnect(websocket)

@app.get("/api/health")
async def health_check():
    """Production diagnostic health monitor validating DB, mode, and memory."""
    try:
        # Measure system resources
        process = psutil.Process(os.getpid())
        memory_rss_mb = round(process.memory_info().rss / 1024 / 1024, 2)
        
        # Check database connectivity dynamically
        db_status = "offline_fallback" if database.is_fallback_mode else "connected"
        db_mode = "sqlite_fallback" if database.is_fallback_mode else "postgresql"
        
        return {
            "success": True,
            "status": "online",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "environment": config.ENV,
            "database": {
                "status": "healthy",
                "mode": db_mode,
                "pool": db_status
            },
            "ai_mode": "offline_simulation" if config.IS_MOCK_MODE else "openai_vision_api",
            "process": {
                "uptime_seconds": int(time.time() - server_boot_time),
                "memory_rss_mb": memory_rss_mb
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "success": False,
            "error": f"Diagnostics failure: {str(e)}"
        }

if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 Starting Uvicorn development server on port {config.PORT}...")
    
    # On Windows, Uvicorn's reload=True forces SelectorEventLoop, which does not support
    # the asynchronous subprocess execution required by Playwright (NotImplementedError).
    # Therefore, we automatically disable reload on Windows.
    is_windows = sys.platform == "win32"
    
    # Allow overriding reload behavior via environment variable
    reload_env = os.getenv("UVICORN_RELOAD")
    if reload_env is not None:
        use_reload = reload_env.lower() == "true"
    else:
        use_reload = not is_windows
        
    if is_windows and use_reload:
        logger.warning(
            "⚠️ Auto-reload is enabled on Windows. This may override the event loop policy "
            "to SelectorEventLoop and cause Playwright to crash with NotImplementedError!"
        )
    elif is_windows:
        logger.info(
            "ℹ️ Running on Windows: Auto-reload disabled by default to enable Playwright ProactorEventLoop compatibility. "
            "Set environment variable UVICORN_RELOAD=true to override."
        )
        
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=config.PORT, reload=use_reload)
