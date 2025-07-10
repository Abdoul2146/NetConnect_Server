from fastapi import WebSocket
from typing import Dict
import json
import socket


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[username] = websocket
        print(f"{username} connected.")

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]
            print(f"{username} disconnected.")

    async def send_personal_message(self, message, username: str):
        try:
            if username in self.active_connections:
                await self.active_connections[username].send_json(message)
                print(f"Active connections: {list(self.active_connections.keys())}")
                print(f"Sending to: {username}")
        except Exception as e:
            print(f"Error sending message to {username}: {str(e)}")
            self.disconnect(username)

    async def broadcast(self, message: str, exclude: str = None):
        for user, connection in list(self.active_connections.items()):
            if user != exclude:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"Error broadcasting to {user}: {e}")


manager = ConnectionManager()