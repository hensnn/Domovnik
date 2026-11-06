"""Soubory: audit změn a ochrana integrity vazeb (F4)

- audit trigger na ``files`` a ``file_links`` (kdo co nahrál, připojil, odpojil),
- jedna vazba téhož souboru na tutéž věc / umístění,
- nejvýše jedna vazba s rolí ``primary`` na věc / umístění.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX file_links_item_file_uq ON file_links (item_id, file_id) "
        "WHERE item_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX file_links_loc_file_uq ON file_links (location_id, file_id) "
        "WHERE location_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX file_links_item_primary_uq ON file_links (item_id) "
        "WHERE role = 'primary' AND item_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX file_links_loc_primary_uq ON file_links (location_id) "
        "WHERE role = 'primary' AND location_id IS NOT NULL"
    )
    op.execute(
        "CREATE TRIGGER files_audit_trg AFTER INSERT OR UPDATE OR DELETE ON files "
        "FOR EACH ROW EXECUTE FUNCTION audit_row()"
    )
    op.execute(
        "CREATE TRIGGER file_links_audit_trg AFTER INSERT OR UPDATE OR DELETE ON file_links "
        "FOR EACH ROW EXECUTE FUNCTION audit_row()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS file_links_audit_trg ON file_links")
    op.execute("DROP TRIGGER IF EXISTS files_audit_trg ON files")
    op.execute("DROP INDEX IF EXISTS file_links_loc_primary_uq")
    op.execute("DROP INDEX IF EXISTS file_links_item_primary_uq")
    op.execute("DROP INDEX IF EXISTS file_links_loc_file_uq")
    op.execute("DROP INDEX IF EXISTS file_links_item_file_uq")
