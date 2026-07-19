from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@dataclass(slots=True)
class Database:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    @classmethod
    def connect(cls, url: str, *, echo: bool = False) -> Database:
        engine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        return cls(engine=engine, sessions=sessions)

    async def close(self) -> None:
        await self.engine.dispose()
