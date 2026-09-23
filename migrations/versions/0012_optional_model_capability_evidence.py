"""Allow public model capability evidence to be omitted."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_optional_model_capability_evidence"
down_revision: str | None = "0011_public_model_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "model_capabilities",
        "evidence",
        existing_type=sa.String(length=1024),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "model_capabilities",
        "evidence",
        existing_type=sa.String(length=1024),
        nullable=False,
    )
