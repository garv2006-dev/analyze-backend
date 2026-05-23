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
    
    logger.info(f"🔌 Attempting to connect to PostgreSQL at {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}...")
    
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
        logger.warning(f"⚠️ NOTE: Logs will be persisted locally inside 'backend/fallback.db'!")
        logger.warning(f"⚠️ =======================================================\n")
        
        # Fall back to SQLite database using aiosqlite
        is_fallback_mode = True
        sqlite_db_path = config.BACKEND_DIR / "fallback.db"
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
