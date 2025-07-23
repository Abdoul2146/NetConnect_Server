from sqlalchemy import Table, Column, Integer, String, DateTime, ForeignKey, Text, Boolean, UniqueConstraint
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
    is_online = Column(Boolean, default=False)

    messages_sent = relationship("Message", back_populates="sender", foreign_keys='Message.sender_id')
    messages_received = relationship("Message", back_populates="receiver", foreign_keys='Message.receiver_id')


class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey('users.id'))
    receiver_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # null means broadcast
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)  # 0 for unread, 1 for read

    file_path = Column(String, nullable=True)  # path or URL to file attachment
    file_type = Column(String, nullable=True)  # mime-type like 'image/png', 'application/pdf'
    # forwarded_from_id = Column(Integer, ForeignKey('messages.id'), nullable=True)  # Add this line
    forwarded_from_type = Column(String, nullable=True)
    forwarded_from_content = Column(Text, nullable=True)
    forwarded_from_sender = Column(String, nullable=True)
    forwarded_from_timestamp = Column(DateTime, nullable=True)

    sender = relationship("User", back_populates="messages_sent", foreign_keys=[sender_id])
    receiver = relationship("User", back_populates="messages_received", foreign_keys=[receiver_id])
    # forwarded_from = relationship("Message", remote_side=[id], uselist=False)  # Optional: for ORM access

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
    is_read = Column(Boolean, default=False)  # 0 for unread, 1 for read
    # forwarded_from_id = Column(Integer, ForeignKey('group_messages.id'), nullable=True)  # Add this line
    forwarded_from_type = Column(String, nullable=True)
    forwarded_from_content = Column(Text, nullable=True)
    forwarded_from_sender = Column(String, nullable=True)
    forwarded_from_timestamp = Column(DateTime, nullable=True)

    group = relationship("Group", backref="messages")
    sender = relationship("User")
    # forwarded_from = relationship("GroupMessage", remote_side=[id], uselist=False)  # Optional: for ORM access

class GroupMessageRead(Base):
    __tablename__ = 'group_message_reads'

    id = Column(Integer, primary_key=True, index=True)
    group_message_id = Column(Integer, ForeignKey('group_messages.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    is_read = Column(Boolean, default=False)  # 0 for unread, 1 for read

    group_message = relationship("GroupMessage", backref="reads")
    user = relationship("User", backref="group_message_reads")

    __table_args__ = (UniqueConstraint('group_message_id', 'user_id', name='unique_group_message_read'),)  # Ensure one read per user per message