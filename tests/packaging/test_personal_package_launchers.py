from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_deb_launchers_use_installed_absolute_runtime_root() -> None:
    for name in ("media-bridge-personal-web", "media-bridge-personal-data"):
        source = (ROOT / "packaging/deb" / name).read_text(encoding="utf-8")
        assert "/opt/media-bridge/app" in source
        assert "/opt/media-bridge/runtime/bin/python" in source
        assert "dirname -- " not in source
