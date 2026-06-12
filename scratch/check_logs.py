import asyncio
import sys
from pathlib import Path

# Add root folder to python path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from backend.app import database
from backend.app.models.log import Log
from sqlalchemy.future import select

async def main():
    await database.init_database()
    async with database.SessionLocal() as session:
        result = await session.execute(
            select(Log)
            .where(Log.event_type.in_(["AUTH_REGISTER", "AUTH_LOGIN_FAILED", "AUTH_LOGIN", "AUTH_LOGIN_BLOCKED"]))
            .order_by(Log.timestamp.desc())
        )
        logs = result.scalars().all()
        print(f"Total auth logs found: {len(logs)}")
        for l in logs:
            print(f"Time: {l.timestamp}, Event: {l.event_type}, Msg: {l.message}")

if __name__ == "__main__":
    asyncio.run(main())
