import asyncio
from abc import ABC, abstractmethod
from typing import Dict, TypeVar, get_type_hints

from sqlalchemy.ext.asyncio import AsyncSession

from sqlargon import Database, SQLAlchemyRepository

U = TypeVar("U", bound="AbstractUoW")


class AbstractUoW(ABC):
    @abstractmethod
    async def __aenter__(self: U) -> U:
        raise NotImplementedError

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def rollback(self) -> None:
        raise NotImplementedError


class SQLAlchemyUnitOfWork(AbstractUoW):
    def __init__(
        self,
        db: Database,
        autocommit: bool = True,
        raise_on_exc: bool = True,
    ) -> None:
        self.db = db
        self.autocommit = autocommit
        self.raise_on_exc = raise_on_exc
        self._repositories: Dict[str, SQLAlchemyRepository] = {}

    async def __aenter__(self):
        self.db.set_current_session()
        return self

    @property
    def session(self) -> AsyncSession:
        session = self.db.current_session
        if session is None:
            raise AttributeError("Session context is not set")
        return session

    async def _close(self, *exc) -> None:
        try:
            if exc:
                await self.session.rollback()
            elif self.autocommit:
                await self.commit()
        finally:
            await self.session.close()
            self.db.current_session = None

    async def __aexit__(self, *exc) -> None:
        task = asyncio.create_task(self._close(*exc))
        await asyncio.shield(task)

    async def commit(self) -> None:
        try:
            await self.session.commit()
        except:  # noqa
            await self.session.rollback()
            if self.raise_on_exc:
                raise

    async def rollback(self) -> None:
        await self.session.rollback()

    def __getattr__(self, item: str) -> SQLAlchemyRepository:
        if item not in self._repositories:
            repository_cls = get_type_hints(self).get(item)
            if repository_cls is None:
                raise AttributeError("Could not resolve type annotation for %s", item)
            self._repositories[item] = repository_cls(self.db)
        return self._repositories[item]
