from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.database import Base, engine, SessionLocal
from app.models import User  # Import your User model for the background task
from app.websocket_manager import manager  # Import WebSocket manager
from app.routes import users, messages, groups, files, websocket, notice_board  # ✅ import all route modules here
from fastapi.middleware.cors import CORSMiddleware
from app.authj import jwt_handler  # Import JWT handler for authentication
import uvicorn
import socket
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from sqlalchemy.orm import Session


# Define the background task for status cleanup
async def background_status_cleanup(db_session_factory, interval_seconds=60, inactive_threshold_minutes=5):
    """
    Periodically checks users' last_active_at timestamp.
    If a user is marked online but has been inactive for longer than inactive_threshold_minutes,
    they are marked offline in the database and their status is broadcast.
    """
    print("Starting background status cleanup task...")
    while True:
        await asyncio.sleep(interval_seconds) # Wait for the specified interval before checking again
        
        # Get a new database session for this task's operation
        # This is crucial for long-running background tasks to avoid session staleness.
        db: Session = db_session_factory()
        try:
            # Define the threshold for inactivity
            # All timestamps should ideally be UTC for consistency
            threshold_time = datetime.utcnow() - timedelta(minutes=inactive_threshold_minutes)

            # Query for users who are currently online but haven't been active recently
            stale_users = db.query(User).filter(
                User.is_online == True,
                User.last_active_at < threshold_time
            ).all()

            for user in stale_users:
                user.is_online = False # Mark them offline
                db.commit() # Commit changes for this user (or you can batch commits)
                print(f"User {user.username} marked offline due to inactivity (last active: {user.last_active_at.strftime('%Y-%m-%d %H:%M:%S UTC')}).")
                
                # Broadcast this status change to all other active WebSocket clients
                # Use asyncio.create_task to not block the cleanup loop while broadcasting
                asyncio.create_task(manager.broadcast_status(user.username, "offline", exclude=None))
            
        except Exception as e:
            # Log any errors that occur during the cleanup process
            print(f"Error in background_status_cleanup: {e}")
            db.rollback() # Rollback any changes if an error occurred in the current iteration
        finally:
            # Always close the database session
            db.close()

# Lifespan context manager for startup/shutdown events of the FastAPI application
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application starting up...")

    # Display local IP address at startup
    ip = get_local_ip()
    print(f"Server is running on IP: {ip}")

    # Start the background status cleanup task
    asyncio.create_task(background_status_cleanup(
        db_session_factory=SessionLocal,
        interval_seconds=60,
        inactive_threshold_minutes=5
    ))

    yield

    print("Application shutting down...")


# Initialize FastAPI app
app = FastAPI(lifespan=lifespan)

# origins = [
#     "http://localhost:3000",  # React app running on localhost
#     "http://localhost:8000",  # FastAPI app running on localhost
#     "http://localhost",  # Another potential frontend
# ]

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["*"]for all client sides  Allow all origins, adjust as needed
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Create tables
Base.metadata.create_all(bind=engine)

# Include routers from their correct modules
app.include_router(users.router)
app.include_router(messages.router)
app.include_router(groups.router)
app.include_router(files.router)
app.include_router(websocket.router)  
app.include_router(notice_board.router)  # Include notice board routes

# Mount static file path for file access
app.mount("/uploaded_files", StaticFiles(directory="uploaded_files"), name="uploaded_files")

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

@app.on_event("startup")
async def display_ip():
    ip = get_local_ip()
    print(f"Server is running on IP: {ip}")

@app.get("/")
async def root():
    return {"message": "Welcome to NetChat API"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)