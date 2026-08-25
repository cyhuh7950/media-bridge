import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_images_are_non_root_and_have_no_package_manager_step() -> None:
    for service in ("data", "control"):
        source = (ROOT / "deploy" / "images" / service / "Dockerfile").read_text(
            encoding="utf-8"
        )
        runtime = source.rsplit("FROM ", maxsplit=1)[1]
        assert re.search(r"^USER [1-9][0-9]*:[1-9][0-9]*$", runtime, re.M)
        assert "apt-get" not in runtime
        assert "apk add" not in runtime
        assert "pip install" not in runtime
        assert "HEALTHCHECK" in runtime


def test_runtime_commands_are_service_specific() -> None:
    data = (ROOT / "deploy" / "images" / "data" / "Dockerfile").read_text(encoding="utf-8")
    control = (ROOT / "deploy" / "images" / "control" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert '"media-bridge-gateway"' in data
    assert '"media-bridge-control"' in control
