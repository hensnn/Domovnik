"""Databázové připojení (SQLAlchemy 2, synchronní, psycopg 3)."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

import psycopg
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from domovnik.config import get_settings, to_sqlalchemy_url


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        to_sqlalchemy_url(get_settings().database_url), pool_pre_ping=True, future=True
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def reset_engine() -> None:
    """Zahodí cache engine/sessionmaker (testy, změna DATABASE_URL)."""
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Jednorázová session s commitem při úspěchu (CLI, workery)."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def check_database(url: str) -> bool:
    """Vrátí True, pokud se lze připojit k databázi a odpovídá na dotaz."""
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            row = conn.execute("SELECT 1").fetchone()
            return row is not None and row[0] == 1
    except psycopg.Error:
        return False
