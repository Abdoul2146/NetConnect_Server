# In C:\Users\abdul\Desktop\fastapi\fastapi\netcom\app\database.py

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Define the absolute path to your database file
# This is the most robust way to ensure it always points to the same place.
# os.path.abspath(__file__) -> C:\Users\abdul\Desktop\fastapi\fastapi\netcom\app\database.py
# os.path.dirname(os.path.abspath(__file__)) -> C:\Users\abdul\Desktop\fastapi\fastapi\netcom\app\
DATABASE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netconnect.db")

# Use this absolute path in your SQLAlchemy URL
# The triple slash after sqlite: indicates an absolute path for SQLite
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_FILE_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()