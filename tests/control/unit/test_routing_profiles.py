from uuid import uuid4

import pytest
from pydantic import ValidationError

from media_bridge_control.schemas import RoutingProfileCreate


def test_routing_profile_requires_analysis_and_llm_provider_sets() -> None:
    analysis_id = uuid4()
    llm_id = uuid4()
    profile = RoutingProfileCreate(
        name="default",
        analysis_provider_ids=[analysis_id],
        llm_provider_ids=[llm_id],
        strategy="health",
    )
    assert profile.strategy == "health"


def test_routing_profile_accepts_korean_display_name() -> None:
    profile = RoutingProfileCreate(
        name="기본 문서 분석",
        analysis_provider_ids=[uuid4()],
        llm_provider_ids=[uuid4()],
    )

    assert profile.name == "기본 문서 분석"


def test_routing_profile_rejects_duplicate_provider_ids() -> None:
    provider_id = uuid4()
    with pytest.raises(ValidationError):
        RoutingProfileCreate(
            name="default",
            analysis_provider_ids=[provider_id, provider_id],
            llm_provider_ids=[uuid4()],
        )
