"""Add managed analysis-to-LLM routing profiles."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_routing_profiles"
down_revision: str | None = "0004_managed_provider_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "routing_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("analysis_provider_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("llm_provider_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("strategy", sa.String(16), nullable=False, server_default="priority"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "strategy IN ('priority', 'fallback', 'health', 'cost')",
            name="routing_profiles_strategy_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("routing_profiles")
