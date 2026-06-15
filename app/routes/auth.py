import re
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database import get_db, get_next_sequence
from backend.app.models.user import User
from backend.app.models.log import Log
from backend.app.models.target_url import TargetURL
from backend.app.services.security import hash_password, verify_password, create_access_token, get_current_user

logger = logging.getLogger("AuthRoutes")
logger.setLevel(logging.INFO)

router = APIRouter()

# Pydantic Schemas for Requests/Responses
class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=8)

class LoginRequest(BaseModel):
    email: str = Field(..., max_length=100)
    password: str = Field(...)

class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    created_at: str

def validate_password_strength(password: str) -> Optional[str]:
    """Validates that a password satisfies standard complex strength criteria."""
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return "Password must contain at least one number."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return "Password must contain at least one special character."
    return None

def validate_email_format(email: str) -> bool:
    """Validates email formatting using standard regular expression match."""
    email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(email_regex, email))

@router.post("/register")
async def register(body: RegisterRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Registers a new user after executing strict email format and password strength checks."""
    name = body.name.strip()
    email = body.email.strip().lower()
    password = body.password
    
    # 1. Validate email format
    if not validate_email_format(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format."
        )
        
    # 2. Validate password strength
    password_error = validate_password_strength(password)
    if password_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=password_error
        )
        
    # 3. Check for existing user
    existing_user = await db.users.find_one({"email": email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already registered."
        )
        
    # 4. Hash and save the user
    try:
        # Check if this is the first user; make them 'admin' for convenience
        total_users = await db.users.count_documents({})
        role = "admin" if total_users == 0 else "user"
        
        hashed_pwd = hash_password(password)
        user_id = await get_next_sequence("users")
        now = datetime.now(timezone.utc)
        
        new_user_doc = {
            "id": user_id,
            "name": name,
            "email": email,
            "password_hash": hashed_pwd,
            "role": role,
            "created_at": now,
            "updated_at": now
        }
        await db.users.insert_one(new_user_doc)
        new_user = User.from_dict(new_user_doc)
        
        # Log successful registration
        audit_id = await get_next_sequence("logs")
        await db.logs.insert_one({
            "id": audit_id,
            "user_id": user_id,
            "event_type": "AUTH_REGISTER",
            "message": f"User '{name}' registered successfully with role '{role}'.",
            "timestamp": now
        })
        
        return {
            "success": True,
            "message": "User registered successfully.",
            "data": new_user.to_dict()
        }
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )

@router.post("/login")
async def login(body: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Authenticates a user, checks login failure rate-limiting, and issues a JWT token."""
    email = body.email.strip().lower()
    password = body.password
    
    # 1. Query user first to check if they exist
    user_doc = await db.users.find_one({"email": email})
    user = User.from_dict(user_doc)
    
    # Find timestamp of the last successful login or registration for this user
    last_success_time = None
    if user:
        last_success_doc = await db.logs.find({
            "user_id": user.id,
            "event_type": {"$in": ["AUTH_LOGIN", "AUTH_REGISTER"]}
        }).sort("timestamp", -1).limit(1).to_list(1)
        
        if last_success_doc:
            last_success_time = last_success_doc[0].get("timestamp")

    # 2. Login rate limit attempt check (max 5 failures in 15 mins)
    fifteen_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=15)
    
    # Base filters for login failures
    failure_filters = {
        "event_type": "AUTH_LOGIN_FAILED",
        "message": f"Failed login attempt for email '{email}'.",
        "timestamp": {"$gte": fifteen_mins_ago}
    }
    
    # Only count failures that occurred after the last successful login/registration
    if last_success_time:
        if last_success_time.tzinfo is None:
            last_success_time = last_success_time.replace(tzinfo=timezone.utc)
        failure_filters["timestamp"]["$gt"] = last_success_time
        
    failures = await db.logs.count_documents(failure_filters)
    
    if failures >= 5:
        # Log rate limit block
        block_id = await get_next_sequence("logs")
        await db.logs.insert_one({
            "id": block_id,
            "event_type": "AUTH_LOGIN_BLOCKED",
            "message": f"Brute-force login block triggered for email '{email}'. Exceeded maximum failures.",
            "timestamp": datetime.now(timezone.utc)
        })
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in 15 minutes."
        )

    # 3. Check credentials
    if not user or not verify_password(password, user.password_hash):
        # Log failed attempt
        fail_id = await get_next_sequence("logs")
        await db.logs.insert_one({
            "id": fail_id,
            "event_type": "AUTH_LOGIN_FAILED",
            "message": f"Failed login attempt for email '{email}'.",
            "timestamp": datetime.now(timezone.utc)
        })
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )
        
    # 4. Successful authentication - issue token
    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    
    # Log login success
    success_id = await get_next_sequence("logs")
    await db.logs.insert_one({
        "id": success_id,
        "user_id": user.id,
        "event_type": "AUTH_LOGIN",
        "message": f"User '{user.name}' logged in successfully.",
        "timestamp": datetime.now(timezone.utc)
    })
    
    return {
        "success": True,
        "access_token": access_token,
        "token_type": "bearer",
        "user": user.to_dict()
    }

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Returns profile information for the currently authenticated User, including their active TargetURL."""
    # Find active target URL
    url_doc = await db.target_urls.find_one({"user_id": current_user.id})
    url_row = TargetURL.from_dict(url_doc)
    
    return {
        "success": True,
        "user": current_user.to_dict(),
        "target_url": url_row.to_dict() if url_row else None
    }
