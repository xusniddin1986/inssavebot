"""
Database connection manager using SQLAlchemy async engine.
Supports PostgreSQL (asyncpg) and SQLite (aiosqlite).
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

logger = logging.getLogger(__name__)


class Database:
    """Async database manager."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine: AsyncEngine = None
        self.session_factory: async_sessionmaker = None

    async def connect(self):
        """Create database engine and session factory."""
        # Ensure SQLite directory exists
        if "sqlite" in self.database_url:
            db_path = self.database_url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Engine configuration
        engine_kwargs = {
            "echo": False,
            "pool_pre_ping": True,
        }

        # PostgreSQL specific settings
        if "postgresql" in self.database_url:
            engine_kwargs.update({
                "pool_size": 10,
                "max_overflow": 20,
                "pool_timeout": 30,
                "pool_recycle": 1800,
            })

        self.engine = create_async_engine(self.database_url, **engine_kwargs)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info(f"Database connected: {self.database_url.split('@')[-1]}")

    async def create_tables(self):
        """Create all tables if they don't exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified")

    async def disconnect(self):
        """Close database connection."""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database disconnected")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a transactional database session."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise