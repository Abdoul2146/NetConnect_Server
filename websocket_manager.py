# In websocket_manager.py

from fastapi import WebSocket
from typing import Dict, List # Added List for type hinting in broadcast
import json
from sqlalchemy.orm import Session # Import Session for database operations
from datetime import datetime # Import datetime for last_active_at
import asyncio # Import asyncio if you plan more async operations here

# Assuming you can import your User model and database session here
from app.models import User
from app.database import SessionLocal # Or whatever your session factory is

# It's better to pass the DB session as an argument rather than importing SessionLocal directly
# into manager, as it's typically managed by FastAPI's dependency injection.
# However, for the background task in main.py, SessionLocal will be needed.

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    # Modified connect to accept db session
    async def connect(self, username: str, websocket: WebSocket, db: Session):
        await websocket.accept()
        self.active_connections[username] = websocket
        
        # Update user status in the database on connect
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.is_online = True
            user.last_active_at = datetime.utcnow() # Set last active timestamp in UTC
            db.commit()
            print(f"User {username} connected. Status updated to online.")
            # Broadcast the online status to other users
            await self.broadcast_status(username, "online", exclude=username) # Exclude self from broadcast
        else:
            print(f"Warning: User {username} not found in DB on WebSocket connect.")


    # Modified disconnect to accept db session and be async
    async def disconnect(self, username: str, db: Session):
        # Remove connection from active_connections
        if username in self.active_connections:
            del self.active_connections[username]
            print(f"User {username} removed from active connections.")

        # Update user status in the database on disconnect
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.is_online = False
            user.last_active_at = datetime.utcnow() # Update last active timestamp
            db.commit()
            print(f"User {username} disconnected. Status updated to offline.")
            # Broadcast the offline status to other users
            await self.broadcast_status(username, "offline", exclude=username) # Exclude self from broadcast
        else:
            print(f"Warning: User {username} not found in DB on WebSocket disconnect.")

    async def send_personal_message(self, message: Dict, username: str): # Expect message as Dict now
        try:
            if username in self.active_connections:
                await self.active_connections[username].send_json(message)
                # print(f"Active connections: {list(self.active_connections.keys())}") # Keep if useful for debugging
                # print(f"Sending to: {username}") # Keep if useful for debugging
            else:
                print(f"User {username} not in active connections for personal message.")
        except Exception as e:
            print(f"Error sending personal message to {username}: {str(e)}")
            # Consider handling stale connection more robustly,
            # but WebSocketDisconnect in the endpoint should handle most cases.
            # No automatic disconnect here, let the endpoint handle WebSocketDisconnect
            # self.disconnect(username) # Don't call disconnect here as it expects db session

    async def broadcast(self, message: Dict, exclude: str = None): # Expect message as Dict now
        # Create a list from active_connections.items() to avoid RuntimeError during iteration
        # if a connection disconnects while iterating
        for user_name, connection in list(self.active_connections.items()):
            if user_name != exclude:
                try:
                    await connection.send_json(message)
                except RuntimeError as e: # Catch errors if connection is already closed/stale
                    print(f"Error broadcasting to {user_name}: {e}. Connection might be stale.")
                    # If you need to remove stale connections here, you'd need db session
                    # and call await self.disconnect(user_name, db)
                except Exception as e:
                    print(f"Error broadcasting to {user_name}: {e}")

    # Modified broadcast_status to accept exclude parameter
    async def broadcast_status(self, username: str, status: str, exclude: str = None):
        status_message = {
            "type": "status",
            "username": username,
            "status": status
        }
        # Use send_json directly if message is already a dictionary
        await self.broadcast(status_message, exclude=exclude)


manager = ConnectionManager()
