from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_release_and_roadmap_distinguish_v2_and_product_status() -> None:
    documents = [
        ROOT / "docs/superpowers/specs/2026-08-26-media-bridge-v2-interop.md",
        ROOT / "docs/superpowers/plans/2026-08-26-media-bridge-v2-interop-plan.md",
        ROOT / "docs/superpowers/plans/2026-08-24-media-bridge-product-roadmap.md",
        ROOT / "docs/work-status/media-bridge.md",
        ROOT / "docs/releases/0.1.0.md",
        ROOT / "docs/integrations/compatibility-matrix.md",
        ROOT / "docs/manuals/developer/adapters.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in documents)
    assert "V2_CODE_READY_EOUL_CONSUMER_PENDING_APPROVAL" in text
    assert "PRODUCT_NOT_COMPLETE" in text
    assert "0.3.0" in text
    assert "P4_CODE_READY_ISOLATED_LIVE_NOT_VERIFIED" in text
    assert "P5_CODE_READY_REMOTE_HTTPS_NOT_VERIFIED" in text


def test_adapter_docs_do_not_claim_live_install_support() -> None:
    text = (ROOT / "docs/manuals/developer/adapters.md").read_text(encoding="utf-8")
    assert "isolated OpenCodex·OmniRoute source extension" in text
    assert "일반 무수정 Adapter 또는 live 설치 지원으로 표시하지 않는다" in text
