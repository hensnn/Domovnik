"""Příkazová řádka: ``domovnik <příkaz>`` (nebo ``python -m domovnik.cli``)."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from domovnik.context import SYSTEM, ActorContext, bind_context
from domovnik.db import get_sessionmaker, session_scope
from domovnik.services import auth, items

API_DIR = Path(__file__).resolve().parents[2]


def cmd_migrate(_: argparse.Namespace) -> int:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(cfg, "head")
    print("Migrace dokončeny.")
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    password = args.password or os.getenv("DOMOVNIK_ADMIN_PASSWORD") or getpass.getpass("Heslo: ")
    with session_scope() as db:
        bind_context(db, SYSTEM)
        user = auth.create_user(
            db,
            SYSTEM,
            username=args.username,
            display_name=args.display_name or args.username,
            password=password,
            role="admin",
        )
        print(f"Vytvořen administrátor {user.username}.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from domovnik.seed import seed

    with session_scope() as db:
        if items.count_items(db) and not args.force:
            print(
                "Databáze už obsahuje věci. Použij --force, pokud opravdu chceš přidat ukázková data."
            )
            return 1
        ctx = ActorContext(actor_id=None, source="import")
        counts = seed(db, ctx)
    print(f"Hotovo: {counts}")
    return 0


def cmd_files_gc(args: argparse.Namespace) -> int:
    """Smaže nepoužité soubory (bez vazeb a primární fotky) starší než ``--hours``."""
    from datetime import timedelta

    from domovnik.services import files

    db = get_sessionmaker()()
    try:
        bind_context(db, SYSTEM)
        count = files.gc_orphans(db, SYSTEM, older_than=timedelta(hours=args.hours))
        db.commit()
        files.run_pending_deletes(db)  # z disku se maže až po úspěšném commitu
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"Smazáno nepoužitých souborů: {count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="domovnik")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="spustí migrace databáze").set_defaults(func=cmd_migrate)
    p = sub.add_parser("create-admin", help="vytvoří administrátora")
    p.add_argument("--username", required=True)
    p.add_argument("--display-name")
    p.add_argument("--password", help="(nebo DOMOVNIK_ADMIN_PASSWORD, nebo interaktivně)")
    p.set_defaults(func=cmd_create_admin)
    p = sub.add_parser("seed", help="naplní databázi ukázkovými daty (jen vývoj)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_seed)
    p = sub.add_parser("files-gc", help="smaže nepoužité soubory (bez vazeb) z úložiště")
    p.add_argument("--hours", type=int, default=24, help="jen soubory starší než N hodin")
    p.set_defaults(func=cmd_files_gc)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
