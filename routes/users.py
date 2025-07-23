from fastapi import APIRouter, HTTPException, Depends, Form
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from app.auth import hash_password, verify_password
from app.schemas import UserOut
from app.authj.jwt_handler import create_access_token
from app.authj.dependencies import get_current_user
import asyncio
from app.websocket_manager import manager  # Import WebSocket manager

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
        hashed_password=hashed_pw
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
    
    user.is_online = True
    db.commit()

    asyncio.create_task(manager.broadcast_status(username, "online"))  # Broadcast online status via WebSocket manager

    token = create_access_token(data={"sub": user.username})    

    return {"message": "Login successful",
            "username": user.username,
            "access_token": token,
            "token_type": "Bearer"
    }


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

@router.post("/logout")
async def logout(
    username: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_online = False
    db.commit()

    asyncio.create_task(manager.broadcast_status(username, "offline"))  # Broadcast offline status via WebSocket manager

    # Optionally: broadcast status change via WebSocket manager here
    return {"message": "Logout successful", "username": username}
