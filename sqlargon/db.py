from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Callable, Sequence, TypeVar

import sqlalchemy as sa
from sqlalchemy import Executable, Result
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from typing_extensions import ParamSpec

from . import Base
from .settings import DatabaseSettings
from .util import json_dumps, json_loads

try:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
except ImportError:
    SQLAlchemyInstrumentor = None

P = ParamSpec("P")
R = TypeVar("R")


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

            self.insert = staticmethod(insert)
            self.supports_returning = True
            self.supports_on_conflict = True

        elif dialect == "sqlite":
            import sqlite3

            from sqlalchemy.dialects.sqlite import insert

            self.insert = staticmethod(insert)
            self.supports_returning = sqlite3.sqlite_version > "3.35"
            self.supports_on_conflict = True

        if SQLAlchemyInstrumentor is not None:
            SQLAlchemyInstrumentor().instrument(engine=self.engine.sync_engine)

    def set_current_session(self) -> None:
        self.current_session = self.session()

    @property
    def current_session(self) -> AsyncSession:
        s = self._current_session.get()
        if s is None:
            raise AttributeError("Invalid session scope")
        return s

    @current_session.setter
    def current_session(self, value) -> None:
        self._current_session.set(value)

    @current_session.deleter
    def current_session(self) -> None:
        self._current_session.set(None)

    @property
    def in_session_scope(self) -> bool:
        return self._current_session.get() is not None

    async def session_factory(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_maker() as session:
            self.current_session = session
            try:
                yield session
                await session.commit()
            except:  # noqa
                await session.rollback()
                raise
            finally:
                self.current_session = None

    @classmethod
    def from_settings(cls, settings: DatabaseSettings):
        return cls(**settings.to_kwargs())

    @classmethod
    def from_env(cls, **kwargs):
        settings = DatabaseSettings(**kwargs)
        return cls.from_settings(settings)

    @asynccontextmanager
    async def _transaction(self, nested: bool = True):

        if nested:
            async with self.current_session.begin_nested():
                yield
        else:
            async with self.current_session.begin():
                yield

    @asynccontextmanager
    async def transaction(self):
        async with self.current_session.begin_nested() as t:
            yield t

    async def execute_query(self, query: Executable, *args, **kwargs) -> Result:
        if not args or kwargs:
            args, kwargs = self.default_execution_options
        if self.in_session_scope:
            return await self.current_session.execute(query, *args, **kwargs)
        else:
            async with self.session() as session:
                return session.execute(query, *args, **kwargs)

    async def add(self, obj: Model, flush: bool = True) -> None:
        self.current_session.add(obj)
        if flush:
            await self.current_session.flush()

    async def flush(self, objects: Sequence | None = None) -> None:
        await self.current_session.flush(objects)

    async def commit(self, raise_on_exception: bool = True) -> None:
        try:
            await self.current_session.commit()
        except:  # noqa
            await self.current_session.rollback()
            if raise_on_exception:
                raise

    async def stream_scalars(self, query, *args, **kwargs):
        if not args or kwargs:
            args, kwargs = self.default_execution_options
        return await self.current_session.stream_scalars(query, *args, **kwargs)
