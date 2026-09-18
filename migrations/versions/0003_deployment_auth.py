"""Add deployment administrator second-factor state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_deployment_auth"
down_revision: str | None = "0002_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("totp_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("users", "totp_required", server_default=None)
    op.add_column("users", sa.Column("totp_secret_ciphertext", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("recovery_email", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "recovery_email")
    op.drop_column("users", "totp_secret_ciphertext")
    op.drop_column("users", "totp_required")
