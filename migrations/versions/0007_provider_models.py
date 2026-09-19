"""Store optional Provider model overrides."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_provider_models"
down_revision: str | None = "0006_provider_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("model_id", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("providers", "model_id")
