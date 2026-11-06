"""Migrace musí jít nahoru, dolů i znovu nahoru a odpovídat ORM modelům."""

from __future__ import annotations

import os

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from .conftest import API_DIR, BASE_URL, TEST_DB, _swap_db


def test_upgrade_downgrade_upgrade_and_models_match() -> None:
    name = f"{TEST_DB}_mig"
    try:
        with psycopg.connect(BASE_URL, autocommit=True, connect_timeout=3) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {name}")
    except psycopg.Error as exc:
        if os.getenv("CI"):
            raise
        pytest.skip(f"PostgreSQL není dostupný: {exc.__class__.__name__}")

    url = _swap_db(BASE_URL, name)
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.cmd_opts = type("O", (), {"x": [f"url={url}"]})()

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    with psycopg.connect(url) as conn:
        tables = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename <> 'alembic_version'"
        ).fetchone()
        assert tables is not None and tables[0] == 0
    command.upgrade(cfg, "head")

    # každá tabulka z ORM existuje a má všechny namapované sloupce
    from domovnik.db.models import Base

    with psycopg.connect(url) as conn:
        for table in Base.metadata.sorted_tables:
            cols = {
                r[0]
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s",
                    (table.name,),
                )
            }
            assert cols, f"tabulka {table.name} v DB chybí"
            missing = {c.name for c in table.columns} - cols
            assert not missing, f"{table.name}: sloupce {missing} nejsou v DB"

    with psycopg.connect(BASE_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
