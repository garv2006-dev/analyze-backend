import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
import asyncio
from backend.app import config


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Database")

Base = declarative_base()

# Global database states
engine = None
SessionLocal = None
is_fallback_mode = False

async def init_database():
    global engine, SessionLocal, is_fallback_mode
    import os
    from pathlib import Path
    from urllib.parse import urlparse
    
    # In production on Render/Cloud, if no DATABASE_URL is set, avoid trying localhost and fall back to SQLite immediately.
    is_render = os.getenv("RENDER") == "true"
    is_production = config.ENV == "production"
    has_db_url = bool(os.getenv("DATABASE_URL"))
    
    if (is_render or is_production) and not has_db_url:
        logger.warning(
            "\n⚠️ =======================================================\n"
            "⚠️ DATABASE CONFIGURATION WARNING:\n"
            "⚠️ Running in production mode but 'DATABASE_URL' is not set.\n"
            "⚠️ Skipping PostgreSQL connection attempt and falling back directly to SQLite LOCAL DATABASE mode.\n"
            "⚠️ =======================================================\n"
        )
        is_fallback_mode = True
        persistent_dir = Path("/data")
        if persistent_dir.exists() and os.access(persistent_dir, os.W_OK):
            sqlite_db_path = persistent_dir / "fallback.db"
            logger.info(f"💾 Using persistent SQLite database at: {sqlite_db_path}")
        else:
            sqlite_db_path = config.BACKEND_DIR / "fallback.db"
            logger.info(f"💾 Using ephemeral SQLite database at: {sqlite_db_path}")
            
        sqlite_url = f"sqlite+aiosqlite:///{sqlite_db_path}"
        engine = create_async_engine(
            sqlite_url,
            connect_args={"check_same_thread": False}
        )
    else:
        # Extract clean address for logging
        try:
            url_to_parse = config.ASYNC_DATABASE_URL
            if "@" in url_to_parse:
                parts = url_to_parse.split("@", 1)
                # Reconstruct without credentials
                url_to_parse = parts[0].split("//", 1)[0] + "//" + parts[1]
            
            clean_url = url_to_parse.replace("postgresql+asyncpg://", "http://").replace("postgresql://", "http://")
            parsed = urlparse(clean_url)
            db_address = f"{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
        except Exception:
            db_address = f"{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"

        logger.info(f"🔌 Attempting to connect to PostgreSQL at {db_address}...")
        
        # Try PostgreSQL first
        try:
            # Create async engine for PostgreSQL (using asyncpg)
            pg_engine = create_async_engine(
                config.ASYNC_DATABASE_URL,
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=10,
                max_overflow=20
            )
            
            # Test connection by executing a quick query
            async with pg_engine.connect() as conn:
                await conn.execute(text("SELECT 1")) # dummy test
            
            engine = pg_engine
            is_fallback_mode = False
            logger.info("✔️ Successfully connected to PostgreSQL.")
            
        except Exception as pg_error:
            logger.warning(f"\n⚠️ =======================================================")
            logger.warning(f"⚠️ DATABASE CONNECTION WARNING:")
            logger.warning(f"⚠️ PostgreSQL connection initialization failed.")
            logger.warning(f"⚠️ Details: {pg_error}")
            logger.warning(f"⚠️ Automatically falling back to SQLite LOCAL DATABASE mode.")
            logger.warning(f"⚠️ NOTE: Logs will be persisted locally inside fallback.db!")
            logger.warning(f"⚠️ =======================================================\n")
            
            # Fall back to SQLite database using aiosqlite
            is_fallback_mode = True
            persistent_dir = Path("/data")
            if persistent_dir.exists() and os.access(persistent_dir, os.W_OK):
                sqlite_db_path = persistent_dir / "fallback.db"
                logger.info(f"💾 Using persistent SQLite database at: {sqlite_db_path}")
            else:
                sqlite_db_path = config.BACKEND_DIR / "fallback.db"
                logger.info(f"💾 Using ephemeral SQLite database at: {sqlite_db_path}")
            
            sqlite_url = f"sqlite+aiosqlite:///{sqlite_db_path}"
            
            engine = create_async_engine(
                sqlite_url,
                connect_args={"check_same_thread": False}
            )
        
    # Configure the sessionmaker
    SessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False
    )

# Dependency injection for FastAPI routes
async def get_db():
    if SessionLocal is None:
        await init_database()
        
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
