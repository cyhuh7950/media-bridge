"""Add catalog metadata for managed analysis and LLM providers."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_managed_provider_catalog"
down_revision: str | None = "0003_deployment_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("catalog_id", sa.String(128), nullable=True))
    op.add_column("providers", sa.Column("protocol", sa.String(64), nullable=True))
    op.add_column(
        "providers",
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_constraint("providers_kind_check", "providers", type_="check")
    op.create_check_constraint(
        "providers_kind_check",
        "providers",
        "kind IN ('ocr', 'vision', 'analysis', 'llm')",
    )
    op.alter_column("providers", "capabilities", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    has_managed_rows = bind.execute(
        sa.text(
            "SELECT 1 FROM providers "
            "WHERE kind = 'llm' OR catalog_id IS NOT NULL OR protocol IS NOT NULL "
            "OR capabilities <> '[]'::jsonb LIMIT 1"
        )
    ).first()
    if has_managed_rows is not None:
        raise RuntimeError("cannot_downgrade_managed_provider_catalog_with_data")

    op.drop_constraint("providers_kind_check", "providers", type_="check")
    op.create_check_constraint(
        "providers_kind_check",
        "providers",
        "kind IN ('ocr', 'vision', 'analysis')",
    )
    op.drop_column("providers", "capabilities")
    op.drop_column("providers", "protocol")
    op.drop_column("providers", "catalog_id")
