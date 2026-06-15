import os
import jwt
import hashlib
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database import get_db
from backend.app.models.user import User

logger = logging.getLogger("Security")
logger.setLevel(logging.INFO)

# JWT Parameters
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "aether-secret-key-12345678-monitoring-system-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

security_bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2-HMAC-SHA256 with a unique random salt."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    # Store salt and key in a single string separated by ':'
    return f"{base64.b64encode(salt).decode()}:{base64.b64encode(key).decode()}"

def verify_password(password: str, hashed_password: str) -> bool:
    """Verifies a password against its PBKDF2-HMAC-SHA256 hash."""
    try:
        if not hashed_password or ":" not in hashed_password:
            return False
        salt_b64, key_b64 = hashed_password.split(":")
        salt = base64.b64decode(salt_b64)
        expected_key = base64.b64decode(key_b64)
        actual_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return actual_key == expected_key
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a signed JWT access token containing arbitrary payload data."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    """Decodes and validates a JWT access token, returning the payload if valid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token signature expired.")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT token invalid: {e}")
        return None

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> User:
    """FastAPI dependency to extract and return the authenticated User from request headers."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided."
        )
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token."
        )
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload."
        )
    
    user_doc = await db.users.find_one({"email": email})
    user = User.from_dict(user_doc)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found."
        )
    return user

async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency to enforce administrative authorization guards."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required to access this resource."
        )
    return current_user
