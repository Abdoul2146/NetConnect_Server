from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.database import Base, engine
from app.routes import users, messages, groups, files, websocket  # ✅ import all route modules here
from fastapi.middleware.cors import CORSMiddleware
from app.authj import jwt_handler  # Import JWT handler for authentication
# Initialize FastAPI app

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

@app.get("/")
async def root():
    return {"message": "Welcome to NetChat API"}