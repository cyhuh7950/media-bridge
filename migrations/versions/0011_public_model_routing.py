"""Add Provider aliases and public model to routing bindings."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_public_model_routing"
down_revision: str | None = "0010_previous_csrf_digest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("alias", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE providers SET alias = lower(regexp_replace("
            "coalesce(catalog_id, name), '[^a-zA-Z0-9]+', '-', 'g')) "
            "WHERE alias IS NULL"
        )
    )
    op.create_unique_constraint("uq_providers_alias", "providers", ["alias"])
    op.add_column(
        "model_capabilities",
        sa.Column("routing_profile_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_model_capabilities_routing_profile_id",
        "model_capabilities",
        "routing_profiles",
        ["routing_profile_id"],
        ["id"],
    )
    op.add_column(
        "model_capabilities",
        sa.Column("reasoning_effort", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_capabilities", "reasoning_effort")
    op.drop_constraint(
        "fk_model_capabilities_routing_profile_id",
        "model_capabilities",
        type_="foreignkey",
    )
    op.drop_column("model_capabilities", "routing_profile_id")
    op.drop_constraint("uq_providers_alias", "providers", type_="unique")
    op.drop_column("providers", "alias")
