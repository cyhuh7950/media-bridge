"""Add non-sensitive Gateway connection persistence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_connections"
down_revision: str | None = "0001_control_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("gateway_url", sa.String(2_048), nullable=False),
        sa.Column("credential_secret_ref_kind", sa.String(32), nullable=False),
        sa.Column("credential_secret_ref_identifier", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("status", sa.String(16), server_default="untested", nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.CheckConstraint(
            "credential_secret_ref_kind IN ('env', 'docker_secret', 'external')"
        ),
        sa.CheckConstraint("status IN ('untested', 'ready', 'failed', 'revoked')"),
    )


def downgrade() -> None:
    op.drop_table("connections")
