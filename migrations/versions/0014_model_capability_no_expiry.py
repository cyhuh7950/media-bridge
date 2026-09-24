"""Make model capability validity non-expiring."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_model_no_expiry"
down_revision: str | None = "0013_audit_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("model_capabilities", "expires_at", existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE model_capabilities SET expires_at = reviewed_at WHERE expires_at IS NULL")
    op.alter_column("model_capabilities", "expires_at", existing_type=sa.DateTime(timezone=True), nullable=False)
