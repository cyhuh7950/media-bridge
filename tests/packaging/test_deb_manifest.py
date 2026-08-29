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


def test_deb_build_excludes_omniroute_adapter_tree() -> None:
    source = (ROOT / "packaging" / "deb" / "build.sh").read_text(encoding="utf-8")
    assert 'cp -a "$source_root/media_bridge_adapters"' not in source
    assert 'rm -f "$pkg/opt/media-bridge/app/media_bridge/omniroute_adapter.py"' in source
    assert 'cp -a "$source_root/media_bridge_adapters/opencodex"' in source


def test_deb_build_removes_python_cache_directories() -> None:
    source = (ROOT / "packaging" / "deb" / "build.sh").read_text(encoding="utf-8")
    assert "find \"$pkg\" -type d -name __pycache__" in source


def test_deb_build_removes_editable_development_metadata() -> None:
    source = (ROOT / "packaging" / "deb" / "build.sh").read_text(encoding="utf-8")
    assert "-name '__editable__*.pth'" in source
    assert "-name '*.egg-link'" in source
    assert "nonvision_media_bridge-*.dist-info" in source
