from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.database import Base, engine
from app.routes import users, messages, groups, files, websocket  # ✅ import all route modules here
from fastapi.middleware.cors import CORSMiddleware
from app.authj import jwt_handler  # Import JWT handler for authentication
# Initialize FastAPI app
import uvicorn
import socket

app = FastAPI()



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