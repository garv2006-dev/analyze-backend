import asyncio
import sys
from pathlib import Path

# Add root folder to python path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from backend.app import database
from backend.app.models.user import User
from sqlalchemy.future import select

async def main():
    await database.init_database()
    async with database.SessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        print(f"Total users found: {len(users)}")
        for u in users:
            print(f"ID: {u.id}, Name: {u.name}, Email: {u.email}, Role: {u.role}")

if __name__ == "__main__":
    asyncio.run(main())
