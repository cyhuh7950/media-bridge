"""Associate model capability records with their LLM Provider."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_model_provider"
down_revision: str | None = "0007_provider_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_capabilities",
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "model_capabilities_provider_id_fkey",
        "model_capabilities",
        "providers",
        ["provider_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "model_capabilities_provider_id_fkey",
        "model_capabilities",
        type_="foreignkey",
    )
    op.drop_column("model_capabilities", "provider_id")
