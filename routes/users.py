from fastapi import APIRouter, HTTPException, Depends, Form, Body
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from app.auth import hash_password, verify_password
from app.schemas import UserOut, UserProfile, PasswordResetRequest
from app.authj.jwt_handler import create_access_token
from app.authj.dependencies import get_current_user
import asyncio
from app.websocket_manager import manager  # Import WebSocket manager
from datetime import datetime

router = APIRouter()

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/signup")
def signup(
    name: str = Form(...),
    job_title: str = Form(None),
    email: str = Form(...),
    contact: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    security_answer1: str = Form(...),
    security_answer2: str = Form(...),
    security_answer3: str = Form(...),
    db: Session = Depends(get_db)
):
    # Check if username/email already exists
    if db.query(User).filter((User.username == username) | (User.email == email)).first():
        raise HTTPException(status_code=400, detail="Username or email already registered")

    hashed_pw = hash_password(password)
    user = User(
        name=name,
        job_title=job_title,
        email=email,
        contact=contact,
        username=username,
        hashed_password=hashed_pw,
        security_answer1=hash_password(security_answer1),  # hash here
        security_answer2=hash_password(security_answer2),  # hash here
        security_answer3=hash_password(security_answer3),  # hash here
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User registered successfully", "username": user.username}

@router.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Update is_online and last_active_at on login via REST API
    user.is_online = True
    user.last_active_at = datetime.utcnow() # Add/Update this line
    db.commit()

    # The broadcast_status via manager here is good for immediate notification
    # if the client connects to WebSocket *after* logging in via REST.
    # The WS connect method will also handle this, so it might be redundant
    # if WS connect happens immediately after login. Keep it for safety.
    asyncio.create_task(manager.broadcast_status(username, "online"))

    token = create_access_token(data={"sub": user.username})

    return {"message": "Login successful",
            "username": user.username,
            "access_token": token,
            "token_type": "Bearer"
    }

@router.post("/logout")
async def logout(
    username: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update is_online and last_active_at on logout via REST API
    user.is_online = False
    user.last_active_at = datetime.utcnow() # Add/Update this line
    db.commit()

    # Broadcast offline status
    asyncio.create_task(manager.broadcast_status(username, "offline"))

    return {"message": "Logout successful", "username": username}

@router.get("/profile/{username}")
def get_profile(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "name": user.name,
        "job_title": user.job_title,
        "email": user.email,
        "contact": user.contact,
        "username": user.username,
        "is_online": user.is_online  # <-- Add this line
    }

@router.put("/profile/{username}")
def update_profile(
    username: str,
    name: str = Form(None),
    job_title: str = Form(None),
    email: str = Form(None),
    contact: str = Form(None),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if name:
        user.name = name
    if job_title:
        user.job_title = job_title
    if email:
        # Check for email conflict
        existing_email_user = db.query(User).filter(User.email == email, User.username != username).first()
        if existing_email_user:
            raise HTTPException(status_code=400, detail="Email already used by another user")
        user.email = email
    if contact:
        user.contact = contact

    db.commit()
    db.refresh(user)

    return {
        "message": "Profile updated successfully",
        "profile": {
            "name": user.name,
            "job_title": user.job_title,
            "email": user.email,
            "contact": user.contact,
            "username": user.username
        }
    }

@router.get("/api/users")
def get_users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    users = db.query(User).filter(User.username != current_user.username).all()
    return [
        {
            "name": user.name,
            "job_title": user.job_title,
            "email": user.email,
            "contact": user.contact,
            "username": user.username,
            "is_online": user.is_online  # <-- Add this line
        }
        for user in users
    ]



@router.put("/update-password/{username}")
def update_password(
    username: str,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(current_password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Incorrect current password")

    user.hashed_password = hash_password(new_password)
    db.commit()

    return {"message": "Password updated successfully"}


@router.post("/verify_security_answers")
def verify_security_answers(
    data: dict = Body(...),
    db: Session = Depends(get_db)
):
    username = data.get("username")
    answers = data.get("answers", [])
    if not username or len(answers) != 3:
        raise HTTPException(status_code=400, detail="Invalid data")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Assume user.security_answers is a list of hashed answers in order
    # You should hash/check answers as appropriate for your app
    for i, ans in enumerate(answers):
        if not verify_password(ans, getattr(user, f"security_answer{i+1}")):
            raise HTTPException(status_code=403, detail="Incorrect answers")

    return {"message": "Security answers verified"}

@router.put("/reset-password/{username}")
def reset_password(
    username: str,
    req: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(req.new_password)
    db.commit()
    return {"message": "Password reset successfully"}
