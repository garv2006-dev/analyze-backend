import logging
from motor.motor_asyncio import AsyncIOMotorClient
from backend.app import config

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Database")

# Global database states
client = None
db = None
is_fallback_mode = False  # Maintained for rate limiting compatibility

class Base:
    """Dummy class to maintain backward compatibility with old SQLAlchemy imports."""
    pass

async def init_database():
    global client, db
    logger.info(f"🔌 Connecting to MongoDB Atlas: {config.DATABASE_URL.split('@')[-1]}")
    try:
        # Create Async Motor Client
        client = AsyncIOMotorClient(config.DATABASE_URL)
        db = client[config.DB_NAME]
        
        # Verify connection
        await client.admin.command('ping')
        logger.info("✔️ Successfully connected to MongoDB Atlas.")
    except Exception as e:
        logger.critical(f"❌ Failed to connect to MongoDB Atlas: {e}")
        raise

async def get_db():
    """Dependency injection yielding MongoDB database instance."""
    global db
    if db is None:
        await init_database()
    yield db

class SessionContextManager:
    """Simulates SQLAlchemy AsyncSession Context Manager to keep background tasks intact."""
    async def __aenter__(self):
        global db
        if db is None:
            await init_database()
        return db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # No session cleanups needed for simple motor operations
        pass

def SessionLocal():
    """Wrapper returning SessionContextManager to match SQLAlchemy SessionLocal call interface."""
    return SessionContextManager()

async def get_next_sequence(collection_name: str) -> int:
    """
    Generates a thread-safe, sequential auto-incrementing integer ID for a MongoDB collection.
    Matches standard MongoDB auto-increment patterns.
    """
    global db
    if db is None:
        await init_database()
    
    counter = await db.counters.find_one_and_update(
        {"_id": collection_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    return counter["seq"]
