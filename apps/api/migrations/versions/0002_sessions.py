"""Přihlašovací relace (sessions) + sekvence štítků umístění

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sessions (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          token_hash  text NOT NULL UNIQUE,            -- sha256 cookie tokenu
          csrf_token  text NOT NULL,
          user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          user_agent  text,
          ip          text,
          created_at  timestamptz NOT NULL DEFAULT now(),
          last_seen_at timestamptz NOT NULL DEFAULT now(),
          expires_at  timestamptz NOT NULL
        );
        CREATE INDEX sessions_user_idx ON sessions (user_id);
        CREATE INDEX sessions_expires_idx ON sessions (expires_at);

        CREATE SEQUENCE location_label_seq START 1;
        """
    )


def downgrade() -> None:
    op.execute("DROP SEQUENCE location_label_seq; DROP TABLE sessions;")
