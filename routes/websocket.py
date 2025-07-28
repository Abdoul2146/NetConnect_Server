# In websocket.py

from fastapi import WebSocket, APIRouter, Depends, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from app.models import User, Message, Group, GroupMessage # Ensure User is imported for db operations
from app.websocket_manager import manager # Import your ConnectionManager instance
from datetime import datetime, timezone, timedelta
from app.database import get_db
from app.authj.jwt_handler import verify_jwt_token
import json
import asyncio # Import asyncio for the heartbeat task

router = APIRouter()
# manager = ConnectionManager() # This line should remain commented out or removed, as manager is instantiated in websocket_manager.py

# WAT = timezone(timedelta(hours=1)) # Keep your timezone definition if needed for messages

@router.websocket("/ws/{username}")
async def websocket_endpoint(
    websocket: WebSocket,
    username: str,
    token: str = Query(...),
    db: Session = Depends(get_db) # Inject database session
):
    try:
        # JWT authentication: token must match username
        payload = verify_jwt_token(token)
        if not payload or payload.get("sub") != username:
            print(f"Auth failed - Token sub: {payload.get('sub') if payload else 'None'}, Username: {username}")
            await websocket.close(code=4003)
            return

        # Validate user existence in DB
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"User not found: {username}")
            await websocket.close(code=4004)
            return

        # Connect the user via manager, passing the db session
        await manager.connect(username, websocket, db) # Pass db session here

        # Start a periodic heartbeat message from the server to the client
        # This is optional but can help maintain the connection and verify client presence.
        # The client will respond with "pong" frames automatically.
        # You could also send application-level heartbeats here.
        async def send_heartbeat():
            while True:
                await asyncio.sleep(30) # Send heartbeat every 30 seconds
                try:
                    # Send a simple JSON message as a heartbeat. Client can ignore it.
                    await websocket.send_json({"type": "heartbeat"})
                except WebSocketDisconnect:
                    print(f"Heartbeat: WebSocketDisconnect for {username}")
                    break
                except Exception as e:
                    print(f"Heartbeat error for {username}: {e}")
                    break # Break the loop on other errors

        heartbeat_task = asyncio.create_task(send_heartbeat())


        try:
            while True:
                # Receiving any message implies the client is active,
                # so the server can implicitly update last_active_at.
                # If you need an explicit client-side heartbeat, listen for it here.
                data = await websocket.receive_json()
                event_type = data.get("type")

                # If you sent a client-side heartbeat, update last_active_at here:
                if event_type == "heartbeat":
                    user.last_active_at = datetime.utcnow()
                    db.commit()
                    # print(f"Received client heartbeat from {username}. Last active updated.")
                    continue # Don't process as a regular message

                # Handle message status events (your existing logic)
                if event_type == "message_status":
                    message_id = data.get("message_id")
                    status = data.get("status")  # "delivered" or "seen"
                    
                    msg = db.query(Message).filter(Message.id == message_id).first()
                    if msg and status == "seen":
                        msg.is_read = True
                        db.commit()
                    
                    sender_username = msg.sender.username if msg and msg.sender else None
                    if sender_username:
                        await manager.send_personal_message({
                            "type": "message_status",
                            "message_id": message_id,
                            "status": status
                        }, sender_username)
                    continue

                # Validate message content (your existing logic)
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
                # Use UTC for consistency, or ensure WAT is always correctly applied everywhere
                timestamp = datetime.now(WAT) if 'WAT' in locals() else datetime.utcnow()


                try:
                    if group_name:
                        # Group message (your existing logic)
                        group = db.query(Group).filter(Group.name == group_name).first()
                        if not group:
                            await websocket.send_json({"error": f"Group '{group_name}' not found"})
                            continue
                        group_msg = GroupMessage(
                            group_id=group.id,
                            sender_id=user.id,
                            sender_username=user.username,
                            content=content,
                            file_path=file_path,
                            file_type=file_type,
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
                            # Send group message to all members, excluding the sender only if desired
                            await manager.send_personal_message(formatted, member.username)
                        continue

                    # Direct or broadcast message (your existing logic)
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
                        await manager.send_personal_message(formatted, username) # Send to sender as well
                    else:
                        await manager.broadcast(formatted, exclude=None) # Broadcast to all
                except Exception as e:
                    print(f"Error processing message: {str(e)}")
                    await websocket.send_json({"error": "Failed to process message"})
                    continue
        except WebSocketDisconnect:
            # This block handles graceful and ungraceful client disconnections.
            print(f"WebSocketDisconnect for {username}. Calling manager.disconnect.")
            # Ensure the heartbeat task is cancelled when the WS disconnects
            heartbeat_task.cancel()
            # Pass the db session to manager.disconnect
            await manager.disconnect(username, db)
        except Exception as e:
            # Catch any other unexpected errors in the WebSocket loop
            print(f"Unexpected error in websocket connection for {username}: {str(e)}")
            heartbeat_task.cancel() # Cancel heartbeat task
            # Ensure disconnect is called even on other errors
            await manager.disconnect(username, db) # Pass the db session to manager.disconnect

    except WebSocketDisconnect:
        # This outer block catches WebSocketDisconnects that happen during initial setup (before while True loop)
        print(f"Outer WebSocketDisconnect for {username}. Calling manager.disconnect.")
        # No heartbeat_task to cancel yet, as it's not started.
        await manager.disconnect(username, db) # Pass the db session to manager.disconnect
    except Exception as e:
        # This outer block catches any other unexpected errors during initial setup
        print(f"Unexpected error during websocket setup for {username}: {str(e)}")
        await websocket.close(code=4000) # Generic error code
        # Don't call manager.disconnect here as the connect might not have completed successfully.

