"""Neměnné UPDATE (např. přegenerování search_tsv po změně tagů) nezvyšuje version a nezapisuje audit

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_STRIP = "'search_tsv' - 'updated_at' - 'version'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION touch_row() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (to_jsonb(NEW) - {_STRIP}) = (to_jsonb(OLD) - {_STRIP}) THEN
            NEW.updated_at := OLD.updated_at;
            NEW.version    := OLD.version;
            RETURN NEW;
          END IF;
          NEW.updated_at := now();
          NEW.version    := COALESCE(OLD.version, 0) + 1;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_row() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          rec_id uuid;
        BEGIN
          IF TG_OP = 'UPDATE'
             AND (to_jsonb(NEW) - 'search_tsv') = (to_jsonb(OLD) - 'search_tsv') THEN
            RETURN NULL;   -- žádná skutečná změna
          END IF;
          rec_id := COALESCE((to_jsonb(NEW)->>'id'), (to_jsonb(OLD)->>'id'))::uuid;
          INSERT INTO audit_log (actor_id, source, entity_type, entity_id, action, before, after,
                                 change_set_id, request_id)
          VALUES (
            NULLIF(current_setting('app.actor_id', true), '')::uuid,
            NULLIF(current_setting('app.source', true), ''),
            TG_TABLE_NAME,
            rec_id,
            lower(TG_OP),
            CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) - 'search_tsv' END,
            CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) - 'search_tsv' END,
            NULLIF(current_setting('app.change_set_id', true), '')::uuid,
            NULLIF(current_setting('app.request_id', true), '')
          );
          RETURN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION touch_row() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          NEW.updated_at := now();
          NEW.version    := COALESCE(OLD.version, 0) + 1;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_row() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          rec_id uuid;
        BEGIN
          rec_id := COALESCE((to_jsonb(NEW)->>'id'), (to_jsonb(OLD)->>'id'))::uuid;
          INSERT INTO audit_log (actor_id, source, entity_type, entity_id, action, before, after,
                                 change_set_id, request_id)
          VALUES (
            NULLIF(current_setting('app.actor_id', true), '')::uuid,
            NULLIF(current_setting('app.source', true), ''),
            TG_TABLE_NAME, rec_id, lower(TG_OP),
            CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) - 'search_tsv' END,
            CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) - 'search_tsv' END,
            NULLIF(current_setting('app.change_set_id', true), '')::uuid,
            NULLIF(current_setting('app.request_id', true), '')
          );
          RETURN NULL;
        END $$;
        """
    )
