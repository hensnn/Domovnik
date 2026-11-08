"""Knihovna znalostí pro AI (pravidla uspořádání, zvyky domácnosti)

Tabulka ``ai_knowledge`` obsahuje záznamy, které spravuje admin a které AI dostává
v systémovém promptu (nebo si je dohledá nástrojem). Záznam může navrhnout i AI
(``source = 'ai'``); takový záznam je do schválení adminem vypnutý (``enabled = false``).

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ai_knowledge (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          title       text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
          content     text NOT NULL CHECK (length(btrim(content)) BETWEEN 1 AND 2000),
          topic       text NOT NULL DEFAULT 'other'
                      CHECK (topic IN ('household', 'rules', 'naming', 'other')),
          enabled     boolean NOT NULL DEFAULT true,
          source      text NOT NULL DEFAULT 'admin' CHECK (source IN ('admin', 'ai')),
          sort_order  int NOT NULL DEFAULT 0,
          created_by  uuid REFERENCES users(id) ON DELETE SET NULL,
          created_at  timestamptz NOT NULL DEFAULT now(),
          updated_at  timestamptz NOT NULL DEFAULT now(),
          version     int NOT NULL DEFAULT 1
        )
        """
    )
    op.execute(
        "CREATE INDEX ai_knowledge_order_idx ON ai_knowledge (enabled, sort_order, created_at)"
    )
    op.execute(
        "CREATE TRIGGER ai_knowledge_touch_trg BEFORE UPDATE ON ai_knowledge "
        "FOR EACH ROW EXECUTE FUNCTION touch_row()"
    )
    op.execute(
        "CREATE TRIGGER ai_knowledge_audit_trg AFTER INSERT OR UPDATE OR DELETE "
        "ON ai_knowledge FOR EACH ROW EXECUTE FUNCTION audit_row()"
    )
    _extend_op_check()


OPS_BEFORE = (
    "'create_item','update_item','delete_item','move_item','set_quantity',"
    "'create_location','update_location','move_location','archive_location',"
    "'create_category','update_category','merge_categories','delete_category',"
    "'add_tag','remove_tag','create_custom_field'"
)


def _extend_op_check() -> None:
    op.execute("ALTER TABLE ai_change_ops DROP CONSTRAINT ai_change_ops_op_check")
    op.execute(
        "ALTER TABLE ai_change_ops ADD CONSTRAINT ai_change_ops_op_check "
        f"CHECK (op IN ({OPS_BEFORE},'add_knowledge'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_change_ops WHERE op = 'add_knowledge'")
    op.execute("ALTER TABLE ai_change_ops DROP CONSTRAINT ai_change_ops_op_check")
    op.execute(
        f"ALTER TABLE ai_change_ops ADD CONSTRAINT ai_change_ops_op_check CHECK (op IN ({OPS_BEFORE}))"
    )
    op.execute("DROP TABLE IF EXISTS ai_knowledge")
