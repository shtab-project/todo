from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from shtab_core.db import get_session_factory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SessionFactory = Annotated[
    async_sessionmaker[AsyncSession], Depends(get_session_factory)
]


async def read_session(factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


async def write_session(factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    async with factory.begin() as session:
        yield session


ReadSession = Annotated[AsyncSession, Depends(read_session, scope="function")]
WriteSession = Annotated[AsyncSession, Depends(write_session, scope="function")]
