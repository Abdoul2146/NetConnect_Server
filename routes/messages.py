from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User, Message, Group, GroupMessage
from datetime import datetime, timedelta, timezone
from app.authj.dependencies import get_current_user
from fastapi.responses import FileResponse
import os
from app.websocket_manager import manager

# manager = ConnectionManager()  # Initialize the WebSocket connection manager

router = APIRouter()

WAT = timezone(timedelta(hours=1))  

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/messages/{username1}/{username2}")
def get_conversation(username1: str, username2: str, db: Session = Depends(get_db)):
    user1 = db.query(User).filter(User.username == username1).first()
    user2 = db.query(User).filter(User.username == username2).first()
    if not user1 or not user2:
        raise HTTPException(status_code=404, detail="User not found")

    messages = db.query(Message).filter(
        ((Message.sender_id == user1.id) & (Message.receiver_id == user2.id)) |
        ((Message.sender_id == user2.id) & (Message.receiver_id == user1.id))
    ).order_by(Message.timestamp).all()

    def serialize(msg: Message):
        return {
            "id": msg.id,
            "from": msg.sender.username,
            "to": msg.receiver.username if msg.receiver else None,
            "content": msg.content,
            "file_path": msg.file_path,
            "file_type": msg.file_type,
            "timestamp": msg.timestamp.astimezone(WAT).isoformat(),
            "isMe": msg.sender.username == username1
        }

    return {"messages": [serialize(m) for m in messages]}

@router.post("/messages/send")
def send_message(
    to_username: str = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if len(content) > 1000:
        raise HTTPException(status_code=400, detail="Message too long (max 1000 characters)")
        
    receiver = db.query(User).filter(User.username == to_username).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    message = Message(
        sender_id=current_user.id,
        receiver_id=receiver.id,
        content=content,
        timestamp=datetime.utcnow(WAT)
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    
    return {
        "message": "Message sent successfully",
        "id": message.id,
        "timestamp": message.timestamp.astimezone(WAT).isoformat(),
    }

@router.get("/chats")
def get_user_chats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    chat_previews = []

    # --- Direct Chats ---
    users = db.query(User).filter(User.id != current_user.id).all()
    for user in users:
        last_msg = (
            db.query(Message)
            .filter(
                ((Message.sender_id == current_user.id) & (Message.receiver_id == user.id)) |
                ((Message.sender_id == user.id) & (Message.receiver_id == current_user.id))
         )
            .order_by(Message.timestamp.desc())
            .first()
        )
        if last_msg:
            last_message = last_msg.content
            if last_message is None and last_msg.file_path:
                last_message = f"[File] {last_msg.file_path.split('/')[-1]}"
            elif last_message is None:
                last_message = ""
            chat_previews.append({
                "name": user.name,
                "username": user.username,
                "avatar_url": user.avatar_url or "https://via.placeholder.com/50",
                "last_message": last_message,
                "time_ago": last_msg.timestamp.astimezone(WAT).isoformat(),
                "is_group": False,
                "is_read": True,  # Implement your read/unread logic if needed
            })
    # --- Group Chats ---
    for group in current_user.groups:
        last_msg = (
            db.query(GroupMessage)
            .filter(GroupMessage.group_id == group.id)
            .order_by(GroupMessage.timestamp.desc())
            .first()
        )
        last_message = last_msg.content
        if last_message is None and last_msg.file_path:
            last_message = f"[File] {last_msg.file_path.split('/')[-1]}"
        chat_previews.append({
            "name": group.name,
            "username": group.name,  # Use group id or unique group name
            "avatar_url": getattr(group, "avatar_url", None) or "https://via.placeholder.com/50",
            "last_message": last_message,
            "time_ago": last_msg.timestamp.astimezone(WAT).isoformat(),
            "is_group": True,
            "is_read": True,  # Implement your read/unread logic if needed
        })

    # Sort by last message time (descending)
    chat_previews.sort(key=lambda x: x["time_ago"], reverse=True)
    return chat_previews

@router.post("/messages/send_group")
def send_group_message(
    group_name: str = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group = db.query(Group).filter(Group.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if len(content) > 1000:
        raise HTTPException(status_code=400, detail="Message too long (max 1000 characters)")

    group_msg = GroupMessage(
        group_id=group.id,
        sender_id=current_user.id,
        sender_username=current_user.username,
        content=content,
        timestamp=datetime.utcnow(WAT)
    )
    db.add(group_msg)
    db.commit()
    db.refresh(group_msg)
    return {
        "message": "Group message sent successfully",
        "id": group_msg.id,
        "timestamp": group_msg.timestamp.astimezone(WAT).isoformat(),
    }

@router.get("/groups/{group_name}/messages")
def get_group_messages(
    group_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group = db.query(Group).filter(Group.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    messages = db.query(GroupMessage).filter(GroupMessage.group_id == group.id).order_by(GroupMessage.timestamp).all()

    def serialize(msg: GroupMessage):
        return {
            "id": msg.id,
            "from": msg.sender.username if msg.sender else msg.sender_username or "System",
            "content": msg.content,
            "file_path": msg.file_path,
            "file_type": msg.file_type,
            "sender_username": msg.sender_username,
            "timestamp": msg.timestamp.isoformat(),
            "isMe": msg.sender_id == current_user.id if msg.sender else (msg.sender_username == current_user.username)
        }

    return {"messages": [serialize(m) for m in messages]}



@router.post("/messages/send_file")
async def send_file_message(
    to_username: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    receiver = db.query(User).filter(User.username == to_username).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    # Save file
    file_location = f"uploaded_files/{file.filename}"
    with open(file_location, "wb") as buffer:
        buffer.write(await file.read())

    message = Message(
        sender_id=current_user.id,
        receiver_id=receiver.id,
        content=None,  # No text content for file messages
        file_path=file_location,
        file_type=file.content_type,
        timestamp=datetime.now(WAT)
    )
    db.add(message)
    db.commit()
    db.refresh(message)    

    # --- Real-time delivery via WebSocket ---
    formatted = {
        "type": "direct_message",
        "from": current_user.username,
        "to": to_username,
        "content": None,
        "file_path": file_location,
        "file_type": file.content_type,
        "timestamp": message.timestamp.astimezone(WAT).isoformat(),
        "isMe": False
    }
    print(f"Sending file message via WebSocket to {to_username}: {formatted}")
    await manager.send_personal_message(formatted, to_username)
    await manager.send_personal_message(formatted, current_user.username)
    
    return {
        "message": "File sent successfully",
        "id": message.id,
        "file_path": file_location,
        "file_type": file.content_type,
        "timestamp": message.timestamp.astimezone(WAT).isoformat()
    }


@router.post("/groups/{group_name}/send_file")
async def send_group_file_message(
    group_name: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group = db.query(Group).filter(Group.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Save file to uploaded_files/
    file_location = f"uploaded_files/{file.filename}"
    with open(file_location, "wb") as buffer:
        buffer.write(await file.read())

    group_msg = GroupMessage(
        group_id=group.id,
        sender_id=current_user.id,
        sender_username=current_user.username,
        content=None,  # No text content for file messages
        file_path=file_location,
        file_type=file.content_type,
        timestamp=datetime.now(WAT)
    )
    db.add(group_msg)
    db.commit()
    db.refresh(group_msg)

    # --- Real-time delivery via WebSocket ---
    formatted = {
        "type": "group_message",
        "from": current_user.username,
        "group": group.name,
        "content": None,
        "file_path": file_location,
        "file_type": file.content_type,
        "timestamp": group_msg.timestamp.astimezone(WAT).isoformat(),
        "isMe": False
    }
    for member in group.members:
        print(f"Sending group file message via WebSocket to {member.username}: {formatted}")
        await manager.send_personal_message(formatted, member.username)



    return {
        "message": "Group file sent successfully",
        "id": group_msg.id,
        "file_path": file_location,
        "file_type": file.content_type,        
        "timestamp": group_msg.timestamp.astimezone(WAT).isoformat()
    }

@router.get("/uploaded_files/{filename}")
async def download_file(filename: str):
    file_path = os.path.join("uploaded_files", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)