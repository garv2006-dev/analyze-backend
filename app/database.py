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
    
    is_render = os.getenv("RENDER") == "true"
    is_production = config.ENV == "production"
    has_db_url = bool(os.getenv("DATABASE_URL"))
    db_type = os.getenv("DB_TYPE", "postgres").lower()
    
    if db_type == "sqlite":
        is_fallback_mode = True
        persistent_dir = Path("/data")
        if persistent_dir.exists() and os.access(persistent_dir, os.W_OK):
            sqlite_db_path = persistent_dir / "fallback.db"
            logger.info(f"💾 SQLite mode active. Using persistent SQLite database at: {sqlite_db_path}")
        else:
            sqlite_db_path = config.BACKEND_DIR / "fallback.db"
            logger.info(f"💾 SQLite mode active. Using ephemeral SQLite database at: {sqlite_db_path}")
            
        sqlite_url = f"sqlite+aiosqlite:///{sqlite_db_path}"
        engine = create_async_engine(
            sqlite_url,
            connect_args={"check_same_thread": False}
        )
    elif (is_render or is_production) and not has_db_url:
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
            # Analyze error and host to provide clear troubleshooting advice
            err_msg = str(pg_error)
            hints = []
            
            # Extract host for analysis
            host_lower = ""
            try:
                url_to_parse = config.ASYNC_DATABASE_URL
                if "@" in url_to_parse:
                    host_part = url_to_parse.split("@", 1)[1]
                    host_lower = host_part.split("/", 1)[0].split(":", 1)[0].lower()
            except Exception:
                pass
                
            if "localhost" in host_lower or "127.0.0.1" in host_lower or not host_lower:
                hints.append("👉 HINT: The connection is pointing to 'localhost'. On Render, you must set the 'DATABASE_URL' environment variable in your Render Dashboard to point to your live Render PostgreSQL instance.")
            elif "render.com" in host_lower or "oregon-postgres" in host_lower:
                hints.append("👉 HINT: Connection to Render PostgreSQL was refused. Please verify:")
                hints.append("   1. Is your database active? Render Free databases suspend after 90 days of inactivity.")
                hints.append("   2. Are your Web Service and Database in the same region? If so, use the 'Internal Database URL' for secure, instant connection.")
                hints.append("   3. If using the 'External Database URL', ensure you have added '0.0.0.0/0' to the Access Control List (ACL) in your Render PostgreSQL settings.")
            else:
                hints.append("👉 HINT: Please check if your remote database is online, active, and that credentials and port in 'DATABASE_URL' are correct.")
                
            if "getaddrinfo failed" in err_msg or "Name or service not known" in err_msg:
                hints.append("👉 HINT: The database hostname could not be resolved. Double-check your connection string spelling in the Render Dashboard.")

            logger.warning(f"\n⚠️ =======================================================")
            logger.warning(f"⚠️ DATABASE CONNECTION WARNING:")
            logger.warning(f"⚠️ PostgreSQL connection initialization failed.")
            logger.warning(f"⚠️ Details: {pg_error}")
            for hint in hints:
                logger.warning(f"⚠️ {hint}")
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
