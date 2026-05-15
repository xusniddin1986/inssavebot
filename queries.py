"""
Database queries using Repository pattern.
All database operations go through these functions.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BroadcastMessage, Download, FavoriteSong, MusicSearch, User

logger = logging.getLogger(__name__)


# ─── User Queries ─────────────────────────────────────────────────────────────

async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: Optional[str],
    first_name: str,
    last_name: Optional[str] = None,
    language_code: str = "uz",
) -> Tuple[User, bool]:
    """Get existing user or create new one. Returns (user, created)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user:
        # Update user info
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.last_active = datetime.utcnow()
        return user, False

    user = User(
        id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        language_code=language_code,
    )
    session.add(user)
    return user, True


async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    """Get user by ID."""
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def update_user_language(
    session: AsyncSession, user_id: int, language: str
) -> None:
    """Update user language preference."""
    await session.execute(
        update(User).where(User.id == user_id).values(language_code=language)
    )


async def get_all_users(session: AsyncSession) -> List[User]:
    """Get all non-banned users."""
    result = await session.execute(
        select(User).where(User.is_banned == False)
    )
    return result.scalars().all()


async def get_total_users_count(session: AsyncSession) -> int:
    """Get total number of registered users."""
    result = await session.execute(select(func.count(User.id)))
    return result.scalar_one()


async def get_active_users_count(session: AsyncSession, days: int = 7) -> int:
    """Get users active in last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await session.execute(
        select(func.count(User.id)).where(User.last_active >= cutoff)
    )
    return result.scalar_one()


async def ban_user(session: AsyncSession, user_id: int) -> None:
    """Ban a user."""
    await session.execute(
        update(User).where(User.id == user_id).values(is_banned=True)
    )


async def unban_user(session: AsyncSession, user_id: int) -> None:
    """Unban a user."""
    await session.execute(
        update(User).where(User.id == user_id).values(is_banned=False)
    )


# ─── Download Queries ──────────────────────────────────────────────────────────

async def create_download(
    session: AsyncSession,
    user_id: int,
    platform: str,
    url: str,
    format: str = "video",
    quality: Optional[str] = None,
) -> Download:
    """Create a new download record."""
    download = Download(
        user_id=user_id,
        platform=platform,
        url=url,
        format=format,
        quality=quality,
        status="pending",
    )
    session.add(download)
    await session.flush()
    return download


async def update_download_status(
    session: AsyncSession,
    download_id: int,
    status: str,
    title: Optional[str] = None,
    file_size: Optional[float] = None,
    duration: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update download record status."""
    values = {"status": status}
    if title:
        values["title"] = title
    if file_size is not None:
        values["file_size"] = file_size
    if duration is not None:
        values["duration"] = duration
    if error_message:
        values["error_message"] = error_message

    await session.execute(
        update(Download).where(Download.id == download_id).values(**values)
    )


async def increment_user_downloads(session: AsyncSession, user_id: int) -> None:
    """Increment user download counter."""
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(downloads_count=User.downloads_count + 1)
    )


async def get_total_downloads(session: AsyncSession) -> int:
    """Get total successful downloads count."""
    result = await session.execute(
        select(func.count(Download.id)).where(Download.status == "completed")
    )
    return result.scalar_one()


async def get_popular_platforms(session: AsyncSession, limit: int = 5) -> List[Tuple]:
    """Get most popular download platforms."""
    result = await session.execute(
        select(Download.platform, func.count(Download.id).label("count"))
        .where(Download.status == "completed")
        .group_by(Download.platform)
        .order_by(func.count(Download.id).desc())
        .limit(limit)
    )
    return result.all()


async def get_daily_stats(session: AsyncSession) -> dict:
    """Get today's statistics."""
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())

    downloads_today = await session.execute(
        select(func.count(Download.id)).where(
            Download.created_at >= today_start,
            Download.status == "completed",
        )
    )
    new_users_today = await session.execute(
        select(func.count(User.id)).where(User.created_at >= today_start)
    )

    return {
        "downloads": downloads_today.scalar_one(),
        "new_users": new_users_today.scalar_one(),
    }


# ─── Music Queries ─────────────────────────────────────────────────────────────

async def log_music_search(
    session: AsyncSession, user_id: int, query: str, results_count: int = 0
) -> None:
    """Log music search query."""
    search = MusicSearch(
        user_id=user_id, query=query, results_count=results_count
    )
    session.add(search)


async def get_user_recent_searches(
    session: AsyncSession, user_id: int, limit: int = 5
) -> List[str]:
    """Get user's recent search queries."""
    result = await session.execute(
        select(MusicSearch.query)
        .where(MusicSearch.user_id == user_id)
        .order_by(MusicSearch.created_at.desc())
        .limit(limit)
    )
    return [row[0] for row in result.all()]


async def add_favorite_song(
    session: AsyncSession,
    user_id: int,
    youtube_id: str,
    title: str,
    artist: Optional[str] = None,
    duration: Optional[int] = None,
    thumbnail_url: Optional[str] = None,
) -> FavoriteSong:
    """Add song to user favorites."""
    song = FavoriteSong(
        user_id=user_id,
        youtube_id=youtube_id,
        title=title,
        artist=artist,
        duration=duration,
        thumbnail_url=thumbnail_url,
    )
    session.add(song)
    return song


async def get_user_favorites(
    session: AsyncSession, user_id: int
) -> List[FavoriteSong]:
    """Get user's favorite songs."""
    result = await session.execute(
        select(FavoriteSong)
        .where(FavoriteSong.user_id == user_id)
        .order_by(FavoriteSong.created_at.desc())
        .limit(20)
    )
    return result.scalars().all()


# ─── Broadcast Queries ─────────────────────────────────────────────────────────

async def log_broadcast(
    session: AsyncSession,
    admin_id: int,
    message: str,
    sent_count: int,
    failed_count: int,
) -> BroadcastMessage:
    """Log broadcast message."""
    broadcast = BroadcastMessage(
        admin_id=admin_id,
        message=message,
        sent_count=sent_count,
        failed_count=failed_count,
    )
    session.add(broadcast)
    return broadcast