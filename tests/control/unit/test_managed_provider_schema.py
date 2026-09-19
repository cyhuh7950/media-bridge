from media_bridge_control.schemas import ProviderCreate


def test_catalog_provider_requires_kind_and_secret_reference_only() -> None:
    request = ProviderCreate(
        name="omniroute",
        kind="llm",
        catalog_id="omniroute",
        endpoint="https://omniroute.example/v1",
        protocol="openai-responses",
        capabilities={"text"},
        secret_ref={"kind": "env", "identifier": "OMNIROUTE_API_KEY"},
    )

    assert request.kind == "llm"
    assert request.catalog_id == "omniroute"
    assert request.protocol == "openai-responses"
    assert request.capabilities == {"text"}

