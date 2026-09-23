"""Track the last management editor for mutable configuration records."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_management_audit_fields"
down_revision: str | None = "0012_optional_model_capability_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("providers", "routing_profiles", "model_capabilities", "policies"):
        op.add_column(table, sa.Column("updated_by", sa.String(length=128), nullable=True))


def downgrade() -> None:
    for table in ("policies", "model_capabilities", "routing_profiles", "providers"):
        op.drop_column(table, "updated_by")
