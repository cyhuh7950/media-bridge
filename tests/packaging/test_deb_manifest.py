from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_personal_package_allowlist_excludes_legacy_control_modules() -> None:
    source = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    expected = (
        'include = ["media_bridge", "media_bridge.*", "media_bridge_adapters", '
        '"media_bridge_adapters.*", "media_bridge_gateway", "media_bridge_gateway.*", '
        '"media_bridge_personal", "media_bridge_personal.*"]'
    )
    assert expected in source
    assert 'include = ["media_bridge*"]' not in source


def test_deb_build_does_not_copy_legacy_control_tree() -> None:
    source = (ROOT / "packaging" / "deb" / "build.sh").read_text(encoding="utf-8")
    assert 'cp -a "$source_root/media_bridge_control"' not in source


def test_deb_build_removes_python_cache_directories() -> None:
    source = (ROOT / "packaging" / "deb" / "build.sh").read_text(encoding="utf-8")
    assert "find \"$pkg\" -type d -name __pycache__" in source
