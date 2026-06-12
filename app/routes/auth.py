import re
import logging
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from backend.app.database import get_db
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
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
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
    result = await db.execute(select(User).where(User.email == email))
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already registered."
        )
        
    # 4. Hash and save the user
    try:
        # Check if this is the first user; make them 'admin' for convenience
        count_res = await db.execute(select(func.count(User.id)))
        total_users = count_res.scalar() or 0
        role = "admin" if total_users == 0 else "user"
        
        hashed_pwd = hash_password(password)
        new_user = User(
            name=name,
            email=email,
            password_hash=hashed_pwd,
            role=role
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        # Log successful registration
        audit_log = Log(
            user_id=new_user.id,
            event_type="AUTH_REGISTER",
            message=f"User '{name}' registered successfully with role '{role}'."
        )
        db.add(audit_log)
        await db.commit()
        
        return {
            "success": True,
            "message": "User registered successfully.",
            "data": new_user.to_dict()
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"Registration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )

@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticates a user, checks login failure rate-limiting, and issues a JWT token."""
    email = body.email.strip().lower()
    password = body.password
    
    # 1. Login rate limit attempt check (max 5 failures in 15 mins)
    fifteen_mins_ago = datetime.utcnow() - timedelta(minutes=15)
    failure_count_query = select(func.count(Log.id)).where(
        Log.event_type == "AUTH_LOGIN_FAILED",
        Log.message.like(f"%{email}%"),
        Log.timestamp >= fifteen_mins_ago
    )
    failure_count_res = await db.execute(failure_count_query)
    failures = failure_count_res.scalar() or 0
    
    if failures >= 5:
        # Log rate limit block
        block_log = Log(
            event_type="AUTH_LOGIN_BLOCKED",
            message=f"Brute-force login block triggered for email '{email}'. Exceeded maximum failures."
        )
        db.add(block_log)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in 15 minutes."
        )

    # 2. Query user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    
    if not user or not verify_password(password, user.password_hash):
        # Log failed attempt
        fail_log = Log(
            event_type="AUTH_LOGIN_FAILED",
            message=f"Failed login attempt for email '{email}'."
        )
        db.add(fail_log)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )
        
    # 3. Successful authentication - issue token
    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    
    # Log login success
    success_log = Log(
        user_id=user.id,
        event_type="AUTH_LOGIN",
        message=f"User '{user.name}' logged in successfully."
    )
    db.add(success_log)
    await db.commit()
    
    return {
        "success": True,
        "access_token": access_token,
        "token_type": "bearer",
        "user": user.to_dict()
    }

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Returns profile information for the currently authenticated User, including their active TargetURL."""
    # Find active target URL
    url_res = await db.execute(select(TargetURL).where(TargetURL.user_id == current_user.id))
    url_row = url_res.scalars().first()
    
    return {
        "success": True,
        "user": current_user.to_dict(),
        "target_url": url_row.to_dict() if url_row else None
    }
