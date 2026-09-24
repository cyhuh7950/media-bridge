"""Persist optional reasoning effort for LLM Providers."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_provider_reasoning_effort"
down_revision: str | None = "0008_model_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column("reasoning_effort", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("providers", "reasoning_effort")
