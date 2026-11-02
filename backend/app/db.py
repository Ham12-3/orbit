"""Async database engine and sessions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Database:
    """Owns the engine and session factory. Creating it does not open a connection."""

    def __init__(self, url: str, *, connect_timeout_s: float, command_timeout_s: float) -> None:
        self.engine = create_async_engine(
            url,
            pool_pre_ping=True,
            connect_args={"timeout": connect_timeout_s, "command_timeout": command_timeout_s},
        )
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
