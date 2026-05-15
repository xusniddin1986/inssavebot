"""
Database models using SQLAlchemy ORM.
Supports both PostgreSQL and SQLite.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class User(Base):
    """Telegram user model."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str] = mapped_column(String(8), default="uz")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    downloads_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<User id={self.id} username={self.username}>"


class Download(Base):
    """Download history model."""
    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    format: Mapped[str] = mapped_column(String(16), default="video")
    quality: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    file_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # status: pending, downloading, completed, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    def __repr__(self):
        return f"<Download id={self.id} platform={self.platform} status={self.status}>"


class MusicSearch(Base):
    """Music search history model."""
    __tablename__ = "music_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    query: Mapped[str] = mapped_column(String(256))
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class FavoriteSong(Base):
    """User's favorite songs."""
    __tablename__ = "favorite_songs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    youtube_id: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    artist: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class BroadcastMessage(Base):
    """Admin broadcast messages log."""
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger)
    message: Mapped[str] = mapped_column(Text)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )