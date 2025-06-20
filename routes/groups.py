from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User, Group, GroupMessage
from datetime import datetime, timezone, timedelta
from app.authj.dependencies import get_current_user

WAT = timezone(timedelta(hours=1))  # West Africa Time

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/groups")
def create_group(
    name: str = Form(...),
    member_usernames: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not name.strip():
        raise HTTPException(status_code=400, detail="Group name cannot be empty")
    if not member_usernames.strip():
        raise HTTPException(status_code=400, detail="No members provided")

    if db.query(Group).filter(Group.name == name).first():
        raise HTTPException(status_code=400, detail="Group name already exists")

    usernames = [u.strip() for u in member_usernames.split(",") if u.strip()]
    members = db.query(User).filter(User.username.in_(usernames)).all()
    if len(members) != len(usernames):
        raise HTTPException(status_code=400, detail="One or more users not found")

    group = Group(name=name)
    group.members.extend(members)
    db.add(group)
    db.commit()
    db.refresh(group)

    #broadcast message to all members

    system_message = GroupMessage(
        group_id=group.id,
        sender_id=None,
        content=f"Group '{group.name}' has been created",
        timestamp=datetime.now(WAT),
        is_system=True
    )

    db.add(system_message)
    db.commit()

    return {
        "message": "Group created",
        "group_id": group.id,
        "group_name": group.name,
        "members": [u.username for u in group.members]
    }

@router.get("/my_groups")
def get_my_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return {"groups": [g.name for g in current_user.groups]}