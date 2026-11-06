"""Alembic prostředí. URL se bere z DOMOVNIK/DATABASE_URL (nebo z -x url=...)."""

from alembic import context
from sqlalchemy import create_engine

from domovnik.config import get_settings, to_sqlalchemy_url

config = context.config


def _url() -> str:
    x = context.get_x_argument(as_dictionary=True)
    return to_sqlalchemy_url(x.get("url") or get_settings().database_url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
