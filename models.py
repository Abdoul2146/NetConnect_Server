from sqlalchemy import Table, Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship, backref
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    job_title = Column(String, nullable=True)
    email = Column(String, unique=True, index=True)
    contact = Column(String)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    avatar_url = Column(String, nullable=True)
    messages_sent = relationship("Message", back_populates="sender", foreign_keys='Message.sender_id')
    messages_received = relationship("Message", back_populates="receiver", foreign_keys='Message.receiver_id')


class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey('users.id'))
    receiver_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # null means broadcast
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

    file_path = Column(String, nullable=True)  # path or URL to file attachment
    file_type = Column(String, nullable=True)  # mime-type like 'image/png', 'application/pdf'

    sender = relationship("User", back_populates="messages_sent", foreign_keys=[sender_id])
    receiver = relationship("User", back_populates="messages_received", foreign_keys=[receiver_id])

user_group = Table(
    'user_group',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('group_id', Integer, ForeignKey('groups.id'))
)

class Group(Base):
    __tablename__ = 'groups'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    members = relationship("User", secondary=user_group, backref=backref("groups", lazy="dynamic"))

class GroupMessage(Base):
    __tablename__ = 'group_messages'

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id'))
    sender_id = Column(Integer, ForeignKey('users.id'))
    sender_username = Column(String, nullable=True)
    content = Column(Text)
    file_path = Column(String, nullable=True)  # path or URL to file attachment
    file_type = Column(String, nullable=True)  # mime-type like 'image/png', 'application/pdf'
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_system = Column(Boolean, default=False)  # 0 for user message, 1 for system message

    group = relationship("Group", backref="messages")
    sender = relationship("User")