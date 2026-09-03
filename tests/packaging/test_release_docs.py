from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = (
    "docs/install/docker-compose.md",
    "docs/install/windows-wsl.md",
    "docs/install/linux.md",
    "docs/install/cloud-linux.md",
    "docs/install/https-reverse-proxy.md",
    "docs/manuals/user/getting-started.md",
    "docs/manuals/user/connect-and-test.md",
    "docs/manuals/user/troubleshooting.md",
    "docs/manuals/operator/operations.md",
    "docs/manuals/operator/credentials-snapshots-audit.md",
    "docs/manuals/operator/backup-upgrade.md",
    "docs/manuals/developer/core-mcp-gateway.md",
    "docs/manuals/developer/adapter-sdk.md",
)


def test_release_document_set_is_complete_and_never_claims_live_verification() -> None:
    for relative in REQUIRED:
        path = ROOT / relative
        assert path.is_file(), relative
        source = path.read_text(encoding="utf-8")
        assert "Media Bridge" in source, relative
        assert "PRODUCT_COMPLETE" not in source, relative
def test_https_example_is_opt_in_and_does_not_publish_database() -> None:
    source = (ROOT / "deploy/compose.https-example.yaml").read_text(encoding="utf-8")

    assert "profiles: [https-example]" in source
    assert "media-bridge-db" not in source
    assert "자동 적용하지" in source
