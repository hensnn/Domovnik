"""Inventura (F5b): čas aplikace změn, audit relací a indexy

- ``inventory_sessions.applied_at`` – kdy byly rozdíly z inventury zapsány do dat,
- audit trigger na ``inventory_sessions`` (kdo inventuru založil a uzavřel),
- index pro rychlé hledání otevřených inventur a řádků podle věci.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE inventory_sessions ADD COLUMN applied_at timestamptz")
    op.execute(
        "CREATE INDEX inventory_sessions_status_idx ON inventory_sessions (status, started_at DESC)"
    )
    op.execute("CREATE INDEX inventory_lines_item_idx ON inventory_lines (item_id)")
    op.execute(
        "CREATE TRIGGER inventory_sessions_audit_trg AFTER INSERT OR UPDATE OR DELETE "
        "ON inventory_sessions FOR EACH ROW EXECUTE FUNCTION audit_row()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS inventory_sessions_audit_trg ON inventory_sessions")
    op.execute("DROP INDEX IF EXISTS inventory_lines_item_idx")
    op.execute("DROP INDEX IF EXISTS inventory_sessions_status_idx")
    op.execute("ALTER TABLE inventory_sessions DROP COLUMN IF EXISTS applied_at")
