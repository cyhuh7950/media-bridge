"""Create the Media Bridge Control Plane schema."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_control_plane"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UUID = postgresql.UUID(as_uuid=True)
JSON = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")


def _timestamps(*, updated: bool = False) -> list[sa.Column[object]]:
    columns: list[sa.Column[object]] = [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)
    ]
    if updated:
        columns.append(
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)
        )
    return columns


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(updated=True),
        sa.CheckConstraint("role IN ('admin', 'operator', 'viewer')"),
    )
    op.create_table(
        "recovery_codes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_digest", sa.String(128), nullable=False, unique=True),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "bootstrap_tokens",
        sa.Column("selector", sa.String(32), primary_key=True),
        sa.Column("token_digest", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("selector", sa.String(32), primary_key=True),
        sa.Column("session_digest", sa.String(128), nullable=False),
        sa.Column("csrf_digest", sa.String(128), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "client_credentials",
        sa.Column("selector", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("credential_digest", sa.String(128), nullable=False),
        sa.Column("scopes", JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "providers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("endpoint", sa.String(2048), nullable=False),
        sa.Column("secret_ref_kind", sa.String(32), nullable=False),
        sa.Column("secret_ref_identifier", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(updated=True),
        sa.CheckConstraint("kind IN ('ocr', 'vision', 'analysis')"),
        sa.CheckConstraint("secret_ref_kind IN ('env', 'docker_secret', 'external')"),
    )
    op.create_table(
        "model_capabilities",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("model_id", sa.String(128), nullable=False, unique=True),
        sa.Column("aliases", JSON, nullable=False),
        sa.Column("input_modalities", JSON, nullable=False),
        sa.Column("evidence", sa.String(1024), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "pdf_passthrough_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        *_timestamps(updated=True),
    )
    op.create_table(
        "policies",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("body", JSON, nullable=False),
        *_timestamps(updated=True),
    )
    op.create_table(
        "config_drafts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("body", JSON, nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=False),
        *_timestamps(updated=True),
    )
    op.create_table(
        "signing_keys",
        sa.Column("key_id", sa.String(64), primary_key=True),
        sa.Column("algorithm", sa.String(32), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, unique=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("body", JSON, nullable=False),
        sa.Column("digest", sa.String(128), nullable=False, unique=True),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(64), sa.ForeignKey("signing_keys.key_id"), nullable=False),
        sa.Column("source_draft_id", UUID, sa.ForeignKey("config_drafts.id")),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id")),
        *_timestamps(),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("actor_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(128)),
        sa.Column("details", JSON, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "operational_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(128)),
        sa.Column("policy_version", sa.Integer()),
        sa.Column("status_code", sa.String(64), nullable=False),
        sa.Column("latency_bucket", sa.String(32)),
        sa.Column("size_bucket", sa.String(32)),
        *_timestamps(),
        sa.UniqueConstraint("request_id", "event_type"),
    )
    op.create_index(
        "ix_operational_events_created_at",
        "operational_events",
        ["created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_snapshot_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'snapshots are immutable' USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER snapshots_immutable
        BEFORE UPDATE OR DELETE ON snapshots
        FOR EACH ROW EXECUTE FUNCTION prevent_snapshot_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS snapshots_immutable ON snapshots")
    op.execute("DROP FUNCTION IF EXISTS prevent_snapshot_mutation()")
    op.drop_table("operational_events")
    op.drop_table("audit_events")
    op.drop_table("snapshots")
    op.drop_table("signing_keys")
    op.drop_table("config_drafts")
    op.drop_table("policies")
    op.drop_table("model_capabilities")
    op.drop_table("providers")
    op.drop_table("client_credentials")
    op.drop_table("admin_sessions")
    op.drop_table("bootstrap_tokens")
    op.drop_table("recovery_codes")
    op.drop_table("users")
