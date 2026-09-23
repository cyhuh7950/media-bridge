from media_bridge_control.schemas import CredentialCreate


def test_credential_name_accepts_korean_display_name() -> None:
    value = CredentialCreate(name="임시", scopes={"mcp:invoke"})
    assert value.name == "임시"
