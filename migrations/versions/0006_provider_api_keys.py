"""Store Provider API keys encrypted in the Control Plane database."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_provider_api_keys"
down_revision: str | None = "0005_routing_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("encrypted_api_key", sa.Text(), nullable=True))
    op.create_check_constraint(
        "providers_secret_ref_kind_check",
        "providers",
        "secret_ref_kind IN ('env', 'docker_secret', 'external', 'db')",
    )


def downgrade() -> None:
    op.drop_constraint("providers_secret_ref_kind_check", "providers", type_="check")
    op.drop_column("providers", "encrypted_api_key")
