from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User, Message, Group, GroupMessage, GroupMessageRead
from datetime import datetime, timedelta, timezone
from app.authj.dependencies import get_current_user
from fastapi.responses import FileResponse
import os
from app.websocket_manager import manager

router = APIRouter()

WAT = timezone(timedelta(hours=1))  

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def extract_forwarded_metadata(original):
    return {
        "forwarded_from_type": "group" if isinstance(original, GroupMessage) else "direct",
        "forwarded_from_content": original.content,
        "forwarded_from_sender": getattr(original, "sender_username", None) or (original.sender.username if getattr(original, "sender", None) else None),
        "forwarded_from_timestamp": original.timestamp
    }

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
        forwarded = None
        if msg.forwarded_from_type:
            forwarded = {
                "type": msg.forwarded_from_type,
                "from": msg.forwarded_from_sender,
                "content": msg.forwarded_from_content,
                "timestamp": msg.forwarded_from_timestamp.astimezone(WAT).isoformat() if msg.forwarded_from_timestamp else None
            }
        return {
            "id": msg.id,
            "from": msg.sender.username,
            "to": msg.receiver.username if msg.receiver else None,
            "content": msg.content,
            "file_path": msg.file_path,
            "file_type": msg.file_type,
            "timestamp": msg.timestamp.astimezone(WAT).isoformat(),
            "isMe": msg.sender.username == username1,
            "forwarded_from": forwarded
        }

    return {"messages": [serialize(m) for m in messages]}

@router.post("/messages/send")
async def send_message(
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
        timestamp=datetime.now(WAT)
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    unread_count = db.query(Message).filter(
        Message.sender_id == current_user.id,
        Message.receiver_id == receiver.id,
        Message.is_read == False
    ).count()

    preview = {
        "type": "chat_preview_update",
        "chat_type": "direct",
        "chat_id": receiver.username, 
        "last_message": content,
        "unread_count": unread_count,
        "timestamp": message.timestamp.astimezone(WAT).isoformat(),
        "is_group": False,
    }    

    formatted = {
        "type": "direct_message",
        "id": message.id,
        "from": current_user.username,
        "to": to_username,
        "content": content,
        "file_path": None,
        "file_type": None,
        "timestamp": message.timestamp.astimezone(WAT).isoformat(),
        "isMe": False
    }
    await manager.send_personal_message(formatted, to_username)
    await manager.send_personal_message(formatted, current_user.username)
    await manager.send_personal_message(preview, to_username)
    await manager.send_personal_message(preview, current_user.username)
    await manager.send_personal_message({
        "type": "message_status",
        "message_id": message.id,
        "status": "sent"
    }, current_user.username)
    await manager.send_personal_message({
        "type": "message_status",
        "message_id": message.id,
        "status": "sent"
    }, to_username)
    
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
    group_counts = {}

    # --- Direct Chats ---
    user_ids = db.query(Message.sender_id).filter(Message.receiver_id == current_user.id).union(
        db.query(Message.receiver_id).filter(Message.sender_id == current_user.id)
    ).distinct()
    users = db.query(User).filter(User.id.in_(user_ids)).all()
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
        unread_count = db.query(Message).filter(
            Message.sender_id == user.id,
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).count()

        # --- MODIFIED PREVIEW LOGIC ---
        if last_msg:
            if last_msg.file_path:
                file_name = last_msg.file_path.split("/")[-1]
                if last_msg.content and last_msg.content.strip():
                    last_message = f"{file_name}: {last_msg.content.strip()}"
                else:
                    last_message = file_name
            else:
                last_message = last_msg.content or ""
            # Only set status for messages sent by current user
            if last_msg.sender_id == current_user.id:
                if last_msg.is_read:
                    status = "seen"
                else:
                    # You can add is_delivered if you track it, else default to "sent"
                    status = "sent"
            else:
                status = None
        else:
            last_message = ""
            status = None

        chat_previews.append({
            "name": user.name,
            "username": user.username,
            "avatar_url": user.avatar_url or "https://via.placeholder.com/50",
            "last_message": last_message,
            "time_ago": last_msg.timestamp.astimezone(WAT).isoformat() if last_msg else "",
            "is_group": False,
            "is_read": unread_count == 0,
            "unread_count": unread_count,
            "status": status  # <-- Add this line
        })

    # --- Group Chats ---
    for group in current_user.groups:
        unread_count = db.query(GroupMessage).filter(
            GroupMessage.group_id == group.id,
            GroupMessage.sender_id != current_user.id
        ).outerjoin(
            GroupMessageRead,
            (GroupMessageRead.group_message_id == GroupMessage.id) &
            (GroupMessageRead.user_id == current_user.id)
        ).filter(
            (GroupMessageRead.is_read == False) | (GroupMessageRead.id == None)
        ).count()
        group_counts[group.name] = unread_count

        last_msg = (
            db.query(GroupMessage)
            .filter(GroupMessage.group_id == group.id)
            .order_by(GroupMessage.timestamp.desc())
            .first()
        )
        # --- MODIFIED PREVIEW LOGIC FOR GROUPS ---
        if last_msg:
            if last_msg.file_path:
                file_name = last_msg.file_path.split("/")[-1]
                if last_msg.content and last_msg.content.strip():
                    last_message = f"{file_name}: {last_msg.content.strip()}"
                else:
                    last_message = file_name
            else:
                last_message = last_msg.content or ""
        else:
            last_message = ""
        chat_previews.append({
            "name": group.name,
            "username": group.name,
            "avatar_url": getattr(group, "avatar_url", None) or "https://via.placeholder.com/50",
            "last_message": last_message,
            "time_ago": last_msg.timestamp.astimezone(WAT).isoformat() if last_msg else "",
            "is_group": True,
            "is_read": unread_count == 0,
            "unread_count": unread_count,
        })

    # Sort by last message time (descending)
    chat_previews.sort(key=lambda x: x["time_ago"], reverse=True)
    return chat_previews

@router.post("/messages/mark_read")
def mark_direct_read(
    username: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    sender = db.query(User).filter(User.username == username).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")
    db.query(Message).filter(
        Message.sender_id == sender.id,
        Message.receiver_id == current_user.id,
        Message.is_read == False
    ).update({Message.is_read: True}, synchronize_session=False)
    db.commit()
    return {"status": "success"}

@router.post("/groups/{group_name}/mark_read")
def mark_group_read(
    group_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group = db.query(Group).filter(Group.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    messages = db.query(GroupMessage).filter(
        GroupMessage.group_id == group.id,
        GroupMessage.sender_id != current_user.id
    ).all()
    for msg in messages:
        read = db.query(GroupMessageRead).filter_by(
            group_message_id=msg.id, user_id=current_user.id
        ).first()
        if not read:
            read = GroupMessageRead(
                group_message_id=msg.id, user_id=current_user.id, is_read=True
            )
            db.add(read)
        else:
            read.is_read = True
    db.commit()
    return {"status": "success"}




@router.post("/messages/send_group")
async def send_group_message(
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
        timestamp=datetime.now(WAT)
    )
    db.add(group_msg)
    db.commit()
    db.refresh(group_msg)

    for member in group.members:
    # Calculate unread count for this member
        unread_count = db.query(GroupMessage).filter(
            GroupMessage.group_id == group.id,
            GroupMessage.sender_id != member.id
        ).outerjoin(
            GroupMessageRead,
            (GroupMessageRead.group_message_id == GroupMessage.id) &
            (GroupMessageRead.user_id == member.id)
        ).filter(
            (GroupMessageRead.is_read == False) | (GroupMessageRead.id == None)
        ).count()
    
        preview = {
            "type": "chat_preview_update",
            "chat_type": "group",
            "chat_id": group.name,
            "last_message": group_msg.content,
            "unread_count": unread_count,
            "timestamp": group_msg.timestamp.astimezone(WAT).isoformat(),
            "is_group": True
        }
        await manager.send_personal_message(preview, member.username)

        group_message_payload = {
            "type": "group_message",
            "id": group_msg.id,
            "from": current_user.username,
            "group": group.name,
            "content": content,
            "file_path": None,
            "file_type": None,
            "file_name": None,
            "timestamp": group_msg.timestamp.astimezone(WAT).isoformat(),
            "isMe": False,
            "is_group": True
        }
        print("Group message payload:", group_message_payload)
        await manager.send_personal_message(group_message_payload, member.username)


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
        forwarded = None
        if msg.forwarded_from_type:
            forwarded = {
                "type": msg.forwarded_from_type,
                "from": msg.forwarded_from_sender,
                "content": msg.forwarded_from_content,
                "timestamp": msg.forwarded_from_timestamp.astimezone(WAT).isoformat() if msg.forwarded_from_timestamp else None
            }
        read = db.query(GroupMessageRead).filter_by(
            group_message_id=msg.id,
            user_id=current_user.id,
            is_read=True
        ).first()
        return {
            "id": msg.id,
            "from": msg.sender.username if msg.sender else msg.sender_username or "System",
            "content": msg.content,
            "file_path": msg.file_path,
            "file_type": msg.file_type,
            "sender_username": msg.sender_username,
            "timestamp": msg.timestamp.astimezone(WAT).isoformat(),
            "is_read": bool(read),
            "isMe": msg.sender_id == current_user.id if msg.sender else (msg.sender_username == current_user.username),
            "forwarded_from": forwarded
        }
    return {"messages": [serialize(m) for m in messages]}


@router.post("/messages/send_file")
async def send_file_message(
    to_username: str = Form(...),
    content: str = Form(None),
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
        content=content,  # No text content for file messages
        file_path=file_location,
        file_type=file.content_type,
        timestamp=datetime.now(WAT)
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    unread_count = db.query(Message).filter(
        Message.sender_id == current_user.id,
        Message.receiver_id == receiver.id,
        Message.is_read == False
    ).count()

    preview = {
        "type": "chat_preview_update",
        "chat_type": "direct",
        "chat_id": receiver.username, 
        "last_message": f"[File] {file.filename}",
        "unread_count": unread_count,
        "timestamp": message.timestamp.astimezone(WAT).isoformat(),
        "is_group": False,
        "file_name": file.filename,
    }        

    # --- Real-time delivery via WebSocket ---
    formatted = {
        "type": "direct_message",
        "id": message.id,
        "from": current_user.username,
        "to": to_username,
        "content": content,
        "file_path": file_location,
        "file_type": file.content_type,
        "timestamp": message.timestamp.astimezone(WAT).isoformat(),
        "isMe": False,
        "is_group": False,
        "file_name": file.filename
    }
    print(f"Sending file message via WebSocket to {to_username}: {formatted}")
    await manager.send_personal_message(formatted, to_username)
    await manager.send_personal_message(formatted, current_user.username)
    await manager.send_personal_message(preview, to_username)
    await manager.send_personal_message(preview, current_user.username)
    
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
    content: str = Form(None),
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
        content=content,  # No text content for file messages
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
        "id": group_msg.id,
        "from": current_user.username,
        "group": group.name,
        "content": content,
        "file_path": file_location,
        "file_type": file.content_type,
        "file_name": file.filename,
        "timestamp": group_msg.timestamp.astimezone(WAT).isoformat(),
        "isMe": False,
        "is_group": True
    }
    for member in group.members:
        unread_count = db.query(GroupMessage).filter(
            GroupMessage.group_id == group.id,
            GroupMessage.sender_id != member.id
        ).outerjoin(
            GroupMessageRead,
            (GroupMessageRead.group_message_id == GroupMessage.id) &
            (GroupMessageRead.user_id == member.id)
        ).filter(
            (GroupMessageRead.is_read == False) | (GroupMessageRead.id == None)
        ).count()

        preview = {
            "type": "chat_preview_update",
            "chat_type": "group",
            "chat_id": group.name,
            "last_message": f"[File] {file.filename}",
            "unread_count": unread_count,
            "timestamp": group_msg.timestamp.astimezone(WAT).isoformat(),
            "is_group": True,
            "file_name": file.filename
        }
        print(preview)
        print(formatted)
        await manager.send_personal_message(preview, member.username)
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


@router.post("/messages/forward")
async def forward_message(
    message_id: int = Form(...),
    to_username: str = Form(...),
    source_type: str = Form(...),  # <-- Add this field
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    print(f"incoming forward request: message_id={message_id}, to_username={to_username}, source_type={source_type}, from={current_user.username}")

    # Use source_type to determine which table to check
    if source_type == "group":
        original = db.query(GroupMessage).filter(GroupMessage.id == message_id).first()
    elif source_type == "direct":
        original = db.query(Message).filter(Message.id == message_id).first()
    else:
        raise HTTPException(status_code=400, detail="Invalid source_type")

    if not original:
        raise HTTPException(status_code=404, detail="Original message not found")

    receiver = db.query(User).filter(User.username == to_username).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    metadata = extract_forwarded_metadata(original)
    print(f"[debug] forwarded metadata: {metadata}")

    forwarded = Message(
        sender_id=current_user.id,
        receiver_id=receiver.id,
        content=original.content,
        file_path=original.file_path,
        file_type=original.file_type,
        timestamp=datetime.now(WAT),
        **metadata
    )
    db.add(forwarded)
    db.commit()
    db.refresh(forwarded)

    formatted = {
        "type": "direct_message",
        "id": forwarded.id,
        "from": current_user.username,
        "to": to_username,
        "content": forwarded.content,
        "file_path": forwarded.file_path,
        "file_type": forwarded.file_type,
        "timestamp": forwarded.timestamp.astimezone(WAT).isoformat(),
        "isMe": False,
        "forwarded_from": {
            "type": forwarded.forwarded_from_type,
            "from": forwarded.forwarded_from_sender,
            "content": forwarded.forwarded_from_content,
            "timestamp": forwarded.forwarded_from_timestamp.astimezone(WAT).isoformat() if forwarded.forwarded_from_timestamp else None
        }
    }
    print(f"[debug] outgoing forward payload: {formatted}")
    await manager.send_personal_message(formatted, to_username)
    await manager.send_personal_message(formatted, current_user.username)

    return {"message": "Message forwarded", "id": forwarded.id}

    
@router.post("/groups/{group_name}/forward")
async def forward_group_message(
    group_name: str,
    message_id: int = Form(...),
    source_type: str = Form(...),  # <-- Add this field
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    print(f"incoming group forward request: group_name={group_name}, message_id={message_id}, source_type={source_type}, from={current_user.username}")
    group = db.query(Group).filter(Group.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Use source_type to determine which table to check
    if source_type == "group":
        original = db.query(GroupMessage).filter(GroupMessage.id == message_id).first()
    elif source_type == "direct":
        original = db.query(Message).filter(Message.id == message_id).first()
    else:
        raise HTTPException(status_code=400, detail="Invalid source_type")

    if not original:
        raise HTTPException(status_code=404, detail="Original message not found")
    print(f"[debug] original message for forwarding: id={original.id}, content={original.content}")

    metadata = extract_forwarded_metadata(original)
    print(f"[debug] forwarded metadata: {metadata}")
    forwarded = GroupMessage(
        group_id=group.id,
        sender_id=current_user.id,
        sender_username=current_user.username,
        content=original.content,
        file_path=original.file_path,
        file_type=original.file_type,
        timestamp=datetime.now(),
        **metadata
    )
    db.add(forwarded)
    db.commit()
    db.refresh(forwarded)

    formatted = {
        "type": "group_message",
        "id": forwarded.id,
        "from": current_user.username,
        "group": group.name,
        "content": forwarded.content,
        "file_path": forwarded.file_path,
        "file_type": forwarded.file_type,
        "file_name": None,
        "timestamp": forwarded.timestamp.astimezone(WAT).isoformat(),
        "isMe": False,
        "is_group": True,
        "forwarded_from": {
            "type": forwarded.forwarded_from_type,
            "from": forwarded.forwarded_from_sender,
            "content": forwarded.forwarded_from_content,
            "timestamp": forwarded.forwarded_from_timestamp.astimezone(WAT).isoformat() if forwarded.forwarded_from_timestamp else None
        }
    }
    print(f"[debug] outgoing group forward payload: {formatted}")
    for member in group.members:
        await manager.send_personal_message(formatted, member.username)
        print("Sending group forward payload:", formatted)

    return {"message": "Group message forwarded", "id": forwarded.id}