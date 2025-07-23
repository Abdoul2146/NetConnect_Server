from fastapi import WebSocket, APIRouter, Depends, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from app.models import User, Message, Group, GroupMessage
from app.websocket_manager import manager
from datetime import datetime, timezone, timedelta
from app.database import get_db
from app.authj.jwt_handler import verify_jwt_token
import json

router = APIRouter()
# manager = ConnectionManager()

WAT = timezone(timedelta(hours=1))


@router.websocket("/ws/{username}")
async def websocket_endpoint(
    websocket: WebSocket,
    username: str,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    try:
        # JWT authentication: token must match username
        payload = verify_jwt_token(token)
        if not payload or payload.get("sub") != username:
            print(f"Auth failed - Token sub: {payload.get('sub') if payload else 'None'}, Username: {username}")
            await websocket.close(code=4003)
            return

        # Validate user
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"User not found: {username}")
            await websocket.close(code=4004)
            return

        await manager.connect(username, websocket)
        # await manager.broadcast_status(username, "online")

        try:
            while True:
                data = await websocket.receive_json()
                event_type = data.get("type")

                # Handle message status events
                if event_type == "message_status":
                    message_id = data.get("message_id")
                    status = data.get("status")  # "delivered" or "seen"
                    # Update DB if needed
                    msg = db.query(Message).filter(Message.id == message_id).first()
                    if msg and status == "seen":
                        msg.is_read = True
                        db.commit()
                    # Notify sender
                    sender_username = msg.sender.username if msg and msg.sender else None
                    if sender_username:
                        await manager.send_personal_message({
                            "type": "message_status",
                            "message_id": message_id,
                            "status": status
                        }, sender_username)
                    continue

                # Validate message content
                content = data.get("content")
                if not content or not isinstance(content, str):
                    await websocket.send_json({"error": "Invalid message content"})
                    continue
                if len(content) > 1000:
                    await websocket.send_json({"error": "Message too long (max 1000 characters)"})
                    continue

                to_user = data.get("to")
                group_name = data.get("group")
                file_path = data.get("file_path")
                file_type = data.get("file_type")
                timestamp = datetime.now(WAT)

                try:
                    if group_name:
                        # Group message
                        group = db.query(Group).filter(Group.name == group_name).first()
                        if not group:
                            await websocket.send_json({"error": f"Group '{group_name}' not found"})
                            continue
                        group_msg = GroupMessage(
                            group_id=group.id,
                            sender_id=user.id,
                            sender_username=user.username,
                            content=content,
                            timestamp=timestamp
                        )
                        db.add(group_msg)
                        db.commit()
                        formatted = {
                            "type": "group_message",
                            "from": username,
                            "group": group.name,
                            "content": content,
                            "file_path": file_path,
                            "file_type": file_type,
                            "timestamp": str(timestamp)
                        }
                        for member in group.members:
                            await manager.send_personal_message(formatted, member.username)
                        continue

                    # Direct or broadcast message
                    receiver_id = None
                    if to_user:
                        receiver = db.query(User).filter(User.username == to_user).first()
                        if not receiver:
                            await websocket.send_json({"error": f"User '{to_user}' not found"})
                            continue
                        receiver_id = receiver.id

                    message = Message(
                        sender_id=user.id,
                        receiver_id=receiver_id,
                        content=content,
                        file_path=file_path,
                        file_type=file_type,
                        timestamp=timestamp
                    )
                    db.add(message)
                    db.commit()
                    formatted = {
                        "type": "direct_message" if to_user else "broadcast",
                        "from": username,
                        "to": to_user if to_user else "ALL",
                        "content": content,
                        "file_path": file_path,
                        "file_type": file_type,
                        "timestamp": str(timestamp)
                    }
                    if to_user and receiver_id:
                        await manager.send_personal_message(formatted, to_user)
                        await manager.send_personal_message(formatted, username)
                    else:
                        await manager.broadcast(formatted, exclude=None)
                except Exception as e:
                    print(f"Error processing message: {str(e)}")
                    await websocket.send_json({"error": "Failed to process message"})
                    continue
        except WebSocketDisconnect:
            raise
    except WebSocketDisconnect:
        manager.disconnect(username)
        # await manager.broadcast_status(username, "offline")
        # Update DB status
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.is_online = False
            db.commit()
    except Exception as e:
        print(f"Unexpected error in websocket connection: {str(e)}")
        manager.disconnect(username)
