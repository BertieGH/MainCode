from __future__ import annotations
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings


@lru_cache
def _engine():
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncSession:
    async with _sessionmaker()() as session:
        yield session


@lru_cache
def get_firestore() -> Any:
    """
    Lazy Firestore client. Returns None if google-cloud-firestore is unavailable,
    so the rest of the app can run in tests without GCP creds.
    """
    try:
        from google.cloud import firestore
    except ImportError:
        return None
    settings = get_settings()
    if not settings.gcp_project_id:
        return None
    return firestore.AsyncClient(project=settings.gcp_project_id, database=settings.firestore_database)
