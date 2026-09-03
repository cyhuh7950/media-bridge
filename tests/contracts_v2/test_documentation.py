from pathlib import Path

ROOT = Path(__file__).parents[2]

def test_adapter_docs_do_not_claim_live_install_support() -> None:
    text = (ROOT / "docs/manuals/developer/adapters.md").read_text(encoding="utf-8")
    assert "isolated OpenCodex·OmniRoute source extension" in text
    assert "일반 무수정 Adapter 또는 live 설치 지원으로 표시하지 않는다" in text
