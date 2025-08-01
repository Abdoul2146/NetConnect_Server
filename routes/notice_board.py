from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File, status, Body
from app.websocket_manager import manager
from sqlalchemy.orm import Session
from app.database import SessionLocal # Used in the get_db dependency
from app.models import User, NoticeBoard, NoticePost # Ensure all models are imported
from app.authj.dependencies import get_current_user
from datetime import datetime, timezone # Import timezone for explicit UTC if desired
import os
import uuid


# Define the directory for uploaded files if it's not already defined globally
# This should match where your FastAPI static files are served from.
UPLOAD_DIRECTORY = "uploaded_files" # Ensure this directory exists relative to your app root

# Create the upload directory if it doesn't exist
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

router = APIRouter()

# Dependency to get a database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/notice_boards")
def create_notice_board(
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if db.query(NoticeBoard).filter(NoticeBoard.name == name).first():
        raise HTTPException(status_code=400, detail="Board already exists")
    
    # Ensure created_by_id is set
    board = NoticeBoard(name=name, created_by_id=current_user.id)
    db.add(board)
    db.commit()
    db.refresh(board)
    
    # Optionally, auto-follow the creator
    # Merge current_user into this session before appending
    current_user_in_this_session = db.merge(current_user) # NEW
    if current_user_in_this_session not in board.followers:
        board.followers.append(current_user_in_this_session) # Use the merged object
        db.commit() # Commit again after adding follower
        db.refresh(board) # Refresh board to reflect new follower

    return {"message": "Notice board created", "id": board.id, "name": board.name}

@router.get("/notice_boards")
def list_notice_boards(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    boards = db.query(NoticeBoard).all()
    # It's better to fetch user followers explicitly or eagerly load them
    # to avoid N+1 query problems if 'followers' is not loaded.
    # For many-to-many relationships, ensure backref or secondary table is correctly defined.
    
    # Ensure current_user in board.followers works as expected
    # Depending on your SQLAlchemy setup, 'followers' might not be loaded,
    # leading to implicit queries. Consider using .options(joinedload(NoticeBoard.followers))
    # if you experience performance issues.
    
    # Merge current_user into this session to check is_followed correctly
    current_user_in_this_session = db.merge(current_user) # NEW
    
    return [
        {
            "id": board.id,
            "name": board.name,
            # Ensure 'created_by' relationship is defined in NoticeBoard model
            "admin": board.created_by.username if board.created_by else None,
            "is_followed": current_user_in_this_session in board.followers, # Use the merged object
            "is_admin": board.created_by_id == current_user.id,
        }
        for board in boards
    ]

@router.post("/notice_boards/{board_id}/follow")
def follow_board(
    board_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board = db.query(NoticeBoard).filter(NoticeBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Merge current_user into this session
    current_user_in_this_session = db.merge(current_user) # MODIFIED

    if current_user_in_this_session not in board.followers:
        board.followers.append(current_user_in_this_session) # MODIFIED
        db.commit()
        db.refresh(board) # Refresh board to ensure state is updated for subsequent checks/returns
    return {"message": f"Now following {board.name}"}

@router.post("/notice_boards/{board_id}/unfollow")
def unfollow_board(
    board_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board = db.query(NoticeBoard).filter(NoticeBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    # Merge current_user into this session
    current_user_in_this_session = db.merge(current_user) # MODIFIED

    if current_user_in_this_session in board.followers:
        board.followers.remove(current_user_in_this_session) # MODIFIED
        db.commit()
        db.refresh(board) # Refresh board to ensure state is updated
    return {"message": f"Unfollowed {board.name}"}


@router.post("/notice_boards/{board_id}/posts")
async def create_notice_post(
    board_id: int,
    title: str = Form(...),
    description: str = Form(None),
    attachment: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board = db.query(NoticeBoard).filter(NoticeBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    if board.created_by_id != current_user.id: 
        raise HTTPException(status_code=403, detail="Only the board creator can post")
    
    attachment_path = None
    if attachment:
        # Use original filename (no unique prefix)
        safe_filename = os.path.basename(attachment.filename)
        file_location = os.path.join(UPLOAD_DIRECTORY, safe_filename)
        try:
            with open(file_location, "wb") as buffer:
                buffer.write(await attachment.read())
            attachment_path = file_location  # Store full relative path
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save attachment: {str(e)}")

    post = NoticePost(
        board_id=board_id,
        title=title,
        description=description,
        attachment_path=attachment_path,
        posted_by_id=current_user.id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    for follower in board.followers:
        await manager.send_personal_message({
            "type": "notice_post",
            "board": board.name,
            "title": post.title,
            "description": post.description,
            "timestamp": post.timestamp.isoformat(),
            "attachment_path": post.attachment_path,
            "posted_by": current_user.username
        }, follower.username)

    return {"message": "Post created", "id": post.id, "title": post.title}
    
@router.get("/notice_boards/{board_id}/posts")
def get_board_posts(
    board_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board = db.query(NoticeBoard).filter(NoticeBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    # Merge current_user into this session to check follow status correctly
    current_user_in_this_session = db.merge(current_user) # NEW

    # Check if the user is a follower or the admin of the board
    if current_user_in_this_session not in board.followers and board.created_by_id != current_user_in_this_session.id: # MODIFIED
        raise HTTPException(status_code=403, detail="You must follow this board or be its admin to view posts")
    
    # Ensure 'posted_by' relationship is defined in NoticePost model
    # Consider using .options(joinedload(NoticePost.posted_by)) for eager loading if needed
    posts = db.query(NoticePost).filter(NoticePost.board_id == board_id).order_by(NoticePost.timestamp.desc()).all()
    return [
        {
            "id": post.id,
            "title": post.title,
            "description": post.description,
            "timestamp": post.timestamp.isoformat(),
            "attachment_path": post.attachment_path,
            "posted_by": post.posted_by.username # Ensure this relationship is correct and loaded
        }
        for post in posts
    ]

@router.delete("/notice_posts/{post_id}/delete", status_code=200)
def delete_notice_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    post = db.query(NoticePost).filter(NoticePost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    # Only the poster or board admin can delete
    board = db.query(NoticeBoard).filter(NoticeBoard.id == post.board_id).first()
    if post.posted_by_id != current_user.id and (board and board.created_by_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    if post.attachment_path:
        try:
            os.remove(os.path.join("uploaded_files", post.attachment_path))
        except Exception:
            pass
    db.delete(post)
    db.commit()
    return {"message": "Post deleted successfully"}

@router.put("/notice_posts/{post_id}/edit", status_code=200)
def edit_notice_post(
    post_id: int,
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    post = db.query(NoticePost).filter(NoticePost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    board = db.query(NoticeBoard).filter(NoticeBoard.id == post.board_id).first()
    if post.posted_by_id != current_user.id and (board and board.created_by_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    post.title = data.get("title", post.title)
    post.description = data.get("description", post.description)
    db.commit()
    db.refresh(post)
    return {"message": "Post updated successfully"}