"""Keep the previous CSRF token valid during token rotation."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_previous_csrf_digest"
down_revision: str | None = "0009_provider_reasoning_effort"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admin_sessions",
        sa.Column("previous_csrf_digest", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admin_sessions", "previous_csrf_digest")
