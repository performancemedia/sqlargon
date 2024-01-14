from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, Callable, TypeVar

import sqlalchemy as sa
from sqlalchemy import Executable
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from typing_extensions import ParamSpec

from .orm import Base, ORMModel
from .settings import DatabaseSettings
from .util import json_dumps, json_loads

try:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
except ImportError:
    SQLAlchemyInstrumentor = None

P = ParamSpec("P")
R = TypeVar("R")

M = TypeVar("M", bound=ORMModel)


class Database:
    Model = Base
    Column = sa.Column

    supports_returning: bool = False
    supports_on_conflict: bool = False
    default_execution_options: tuple[tuple, dict] = ((), {})

    insert = staticmethod(sa.insert)
    update = staticmethod(sa.update)
    delete = staticmethod(sa.delete)
    select = staticmethod(sa.select)

    def __init__(
        self,
        url: str,
        json_serializer: Callable[[Any], str] = json_dumps,
        json_deserializer: Callable[[str], Any] = json_loads,
        **kwargs: Any,
    ) -> None:
        self.engine = create_async_engine(
            url=url,
            json_serializer=json_serializer,
            json_deserializer=json_deserializer,
            **kwargs,
        )

        self.session_maker = async_sessionmaker(
            bind=self.engine, expire_on_commit=False
        )
        self.session = asynccontextmanager(self.session_factory)
        self._current_session: ContextVar[AsyncSession | None] = ContextVar(
            "_current_session", default=None
        )

        dialect = self.engine.url.get_dialect().name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert

            self.insert = staticmethod(insert)  # type: ignore[assignment]
            self.supports_returning = True
            self.supports_on_conflict = True

        elif dialect == "sqlite":
            import sqlite3

            from sqlalchemy.dialects.sqlite import insert

            self.insert = staticmethod(insert)  # type: ignore[assignment]
            self.supports_returning = sqlite3.sqlite_version > "3.35"
            self.supports_on_conflict = True

        if SQLAlchemyInstrumentor is not None:
            SQLAlchemyInstrumentor().instrument(engine=self.engine.sync_engine)

    async def create_all(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(self.Model.metadata.create_all)

    async def drop_all(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(self.Model.metadata.drop_all)

    @property
    def in_session_context(self) -> bool:
        return self._current_session.get() is not None

    @property
    def current_session(self):
        return self._current_session.get()

    @current_session.setter
    def current_session(self, session: AsyncSession | None):
        self._current_session.set(session)

    @current_session.deleter
    def current_session(self):
        self._current_session.set(None)

    async def session_factory(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_maker() as session:
            try:
                yield session
                await session.commit()
            except:  # noqa
                await session.rollback()
                raise
            finally:
                await session.close()

    @classmethod
    def from_settings(cls, settings: DatabaseSettings):
        return cls(**settings.to_kwargs())

    @classmethod
    def from_env(cls, **kwargs):
        settings = DatabaseSettings(**kwargs)
        return cls.from_settings(settings)

    async def execute(self, query: Executable, *args, **kwargs):
        if not args or kwargs:
            args, kwargs = self.default_execution_options
        if self.current_session:
            return await self.current_session.execute(query, *args, **kwargs)

        async with self.session() as session:
            return await session.execute(query, *args, **kwargs)

    async def execute_from_connection(self, query: Executable, *args, **kwargs):
        if not args or kwargs:
            args, kwargs = self.default_execution_options
        if self.current_session:
            connection = await self.current_session.connection()
            return await connection.execute(query, *args, **kwargs)

        async with self.session() as session:
            connection = await session.connection()
            return await connection.execute(query, *args, **kwargs)

    async def stream_scalars(self, query, *args, **kwargs):
        if not args or kwargs:
            args, kwargs = self.default_execution_options
        if self.current_session:
            async for row in self._stream_scalars(
                self.current_session, query, *args, **kwargs
            ):
                yield row
        else:
            async with self.session() as session:
                async for row in self._stream_scalars(session, query, *args, **kwargs):
                    yield row

    @staticmethod
    async def _stream_scalars(session, query, *args, **kwargs):
        async with session.stream_scalars(query, *args, **kwargs) as stream:
            async for row in stream:
                yield row
