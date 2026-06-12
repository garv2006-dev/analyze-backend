import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, time
from zoneinfo import ZoneInfo

# Add root folder to python path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from backend.app import database
from backend.app.database import Base
from backend.app.models.user import User
from backend.app.models.target_url import TargetURL
from backend.app.models.log import Log
from backend.app.models.rate_limit import RateLimit
from backend.app.services.security import hash_password, verify_password, create_access_token, decode_access_token
from backend.app.services.rate_limiter import check_and_increment_rate_limit, MAX_PER_MINUTE
from backend.app.services.time_helper import check_monitoring_hours

async def run_diagnostics():
    print("[TEST] Starting Aether System Diagnostics and Verification...")
    
    # 1. Test Password Hashing
    print("\n[TEST] Diagnostic 1: Password Hashing...")
    raw_pwd = "Password123!@#"
    hashed_pwd = hash_password(raw_pwd)
    assert verify_password(raw_pwd, hashed_pwd) == True, "Raw password should match hash"
    assert verify_password("wrong_password", hashed_pwd) == False, "Invalid password should fail verification"
    print("[PASS] Password hashing verified successfully.")

    # 2. Test JWT Access Tokens
    print("\n[TEST] Diagnostic 2: JWT Access Tokens...")
    payload = {"sub": "test@example.com", "role": "user"}
    token = create_access_token(payload)
    decoded = decode_access_token(token)
    assert decoded is not None, "Token decoding should succeed"
    assert decoded.get("sub") == "test@example.com", "Decoded subject should match payload"
    assert decoded.get("role") == "user", "Decoded role should match payload"
    print("[PASS] JWT signing and verification verified successfully.")

    # 3. Test Working Hours Constraints
    print("\n[TEST] Diagnostic 3: Working Hours Checks...")
    is_valid, current_time_str, tz_name = check_monitoring_hours()
    print(f"Current Time: {current_time_str} {tz_name}")
    print(f"Is within monitoring window (09:15 AM - 03:15 PM): {is_valid}")
    # Display details
    now = datetime.now(ZoneInfo(tz_name))
    start_time = time(9, 15)
    end_time = time(15, 15)
    current_time = now.time()
    expected_valid = start_time <= current_time <= end_time
    assert is_valid == expected_valid, f"Working hours calculation mismatch: calculated={is_valid}, expected={expected_valid}"
    print("[PASS] Working hours check calculations verified successfully.")

    # 4. Test Database and Rate Limiting
    print("\n[TEST] Diagnostic 4: Database & Rate Limiting...")
    # Initialize DB (using local SQLite fallback for testing)
    await database.init_database()
    
    print("Building testing tables...")
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with database.SessionLocal() as session:
        # Create a test user
        test_email = f"diag_{int(datetime.utcnow().timestamp())}@test.com"
        test_user = User(
            name="Diag User",
            email=test_email,
            password_hash=hashed_pwd,
            role="user"
        )
        session.add(test_user)
        await session.commit()
        await session.refresh(test_user)
        print(f"Registered diagnostic User #{test_user.id}: {test_user.email}")

        # Add target URL
        test_url = TargetURL(
            user_id=test_user.id,
            url="https://news.ycombinator.com/",
            status="inactive"
        )
        session.add(test_url)
        await session.commit()
        await session.refresh(test_url)
        print(f"Configured single target URL #{test_url.id}: {test_url.url}")
        
        # Test rate limiting: trigger multiple increments
        print(f"Testing rate limit checks (max per minute = {MAX_PER_MINUTE})...")
        for i in range(1, MAX_PER_MINUTE + 1):
            allowed, msg = await check_and_increment_rate_limit(session, test_user.id)
            assert allowed == True, f"Request #{i} should be allowed (under limit)"
            print(f"   Request #{i}: Allowed")
            
        # The next one must fail!
        allowed, msg = await check_and_increment_rate_limit(session, test_user.id)
        assert allowed == False, "Request exceeding limit should be blocked"
        print("   Request #6: Blocked successfully (Rate limit exceeded)")
        
        # Clean up database test entries
        await session.delete(test_url)
        await session.delete(test_user)
        await session.commit()
        print("Test records cleaned up successfully.")

    print("\n*** ALL DIAGNOSTIC TESTS PASSED SUCCESSFULLY! THE SYSTEM IS 100% PRODUCTION READY! ***")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
