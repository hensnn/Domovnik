"""Testovací infrastruktura: skutečný PostgreSQL (ne SQLite), migrace přes Alembic."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from domovnik.config import get_settings, to_sqlalchemy_url
from domovnik.context import ActorContext, bind_context
from domovnik.db import get_engine, reset_engine
from domovnik.db.models import User

API_DIR = Path(__file__).resolve().parent.parent
BASE_URL = os.getenv("DATABASE_URL", "postgresql://domovnik:domovnik_dev@localhost:5432/domovnik")
TEST_DB = os.getenv("DOMOVNIK_TEST_DB", "domovnik_test")  # unikátní per worktree


def _swap_db(url: str, name: str) -> str:
    head, _, _ = url.rpartition("/")
    return f"{head}/{name}"


def _use_url(url: str) -> None:
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture(scope="session")
def test_db_url() -> Iterator[str]:
    """Vytvoří čistou databázi domovnik_test a pustí na ni všechny migrace."""
    original = os.environ.get("DATABASE_URL")
    try:
        with psycopg.connect(BASE_URL, autocommit=True, connect_timeout=3) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    except psycopg.Error as exc:
        if os.getenv("CI"):
            raise
        pytest.skip(f"PostgreSQL není dostupný ({exc.__class__.__name__}) – spusť `pnpm db:up`")
    url = _swap_db(BASE_URL, TEST_DB)
    _use_url(url)
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(cfg, "head")
    yield url
    reset_engine()
    if original is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = original
    get_settings.cache_clear()


@pytest.fixture
def db(test_db_url: str) -> Iterator[Session]:
    """Session v transakci, která se po testu vrátí zpět (služby nikdy necommitují)."""
    connection = get_engine().connect()
    trans = connection.begin()
    session = Session(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture
def user(db: Session) -> User:
    u = User(username="tester", display_name="Tester", password_hash=None, role="admin")
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def ctx(db: Session, user: User) -> ActorContext:
    c = ActorContext(actor_id=user.id, source="ui")
    bind_context(db, c)
    return c


def _truncate_all() -> None:
    with get_engine().begin() as conn:
        tables = conn.execute(
            text(
                "SELECT string_agg(format('%I', tablename), ',') FROM pg_tables "
                "WHERE schemaname='public' AND tablename <> 'alembic_version'"
            )
        ).scalar_one()
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def clean_db(test_db_url: str) -> Iterator[None]:
    """Pro API testy (commitují): před i po testu promaže všechna data."""
    _truncate_all()
    yield
    _truncate_all()  # data z API testů nesmí zasahovat do testů s rollbackem (db)


__all__ = ["to_sqlalchemy_url"]
