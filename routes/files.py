from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from uuid import uuid4
import os
import shutil
from fastapi.responses import FileResponse


from app.database import get_db
from app.models import Message, User

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload/")
async def upload_file(
    sender_username: str = Form(...),
    receiver_username: str = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    sender = db.query(User).filter_by(username=sender_username).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")

    receiver = None
    if receiver_username:
        receiver = db.query(User).filter_by(username=receiver_username).first()
        if not receiver:
            raise HTTPException(status_code=404, detail="Receiver not found")

    file_ext = os.path.splitext(file.filename)[-1]
    file_name = f"{uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    message = Message(
        sender_id=sender.id,
        receiver_id=receiver.id if receiver else None,
        content=None,
        file_path=f"/files/{file_name}",
        file_type=file.content_type,
        timestamp=datetime.utcnow()
    )
    db.add(message)
    db.commit()

    return {
        "status": "success",
        "file_url": f"/files/{file_name}",
        "file_type": file.content_type
    }

