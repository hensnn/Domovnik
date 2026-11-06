"""Počáteční schéma (viz sql/0001_initial.sql; referenční návrh v db/schema.sql)

Revision ID: 0001
Revises:
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parent.parent / "sql" / "0001_initial.sql"


def upgrade() -> None:
    # % se zdvojuje, protože psycopg ho jinak bere jako zástupný znak parametru
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    # Návrat na prázdnou databázi. POZOR: smaže všechna data.
    conn = op.get_bind()
    conn.exec_driver_sql("DROP SCHEMA public CASCADE")
    conn.exec_driver_sql("CREATE SCHEMA public")
    # Alembic po downgrade maže řádek z alembic_version → tabulka musí existovat
    conn.exec_driver_sql(
        "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL PRIMARY KEY)"
    )
    conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('0001')")
