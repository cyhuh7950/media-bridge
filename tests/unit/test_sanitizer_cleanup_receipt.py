from __future__ import annotations

from pathlib import Path

import pytest

from media_bridge.receipts import (
    GateReceiptSigner,
    ReceiptBinding,
    ReceiptValidationError,
)
from media_bridge.sanitizer import SanitizationError, sanitize_model_text
from media_bridge.workspace import CleanupError, TemporaryMediaWorkspace


def test_sanitizer_removes_locators_data_urls_and_binary_blobs() -> None:
    locator = "/srv/media/tenant-a/secret.png"
    binary_blob = "A" * 256
    source = (
        f"Screenshot at {locator}\x00\n"
        "data:image/png;base64,AAAA should not survive\n"
        f"payload={binary_blob}\n"
        "Visible error: database timeout"
    )

    sanitized = sanitize_model_text(source, forbidden_locators=[locator])

    assert locator not in sanitized
    assert "data:image" not in sanitized.lower()
    assert binary_blob not in sanitized
    assert "database timeout" in sanitized
    assert "\x00" not in sanitized


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "data:image/png;base64," + ("A" * 512),
        "A" * 512,
        "\x00\x01\x02",
    ],
)
def test_sanitizer_rejects_output_with_no_safe_text(unsafe_text: str) -> None:
    with pytest.raises(SanitizationError):
        sanitize_model_text(unsafe_text)


def test_sanitizer_rejects_obfuscated_media_data_reference() -> None:
    with pytest.raises(SanitizationError, match="media reference"):
        sanitize_model_text("Visible text followed by data : image/png;base64,\nAAAA")


def test_workspace_cleanup_must_remove_all_materialized_media(tmp_path: Path) -> None:
    workspace = TemporaryMediaWorkspace(parent=tmp_path)
    materialized = workspace.write_bytes("capture.png", b"not-secret-test-bytes")

    assert materialized.exists()
    assert materialized.stat().st_mode & 0o777 == 0o600

    workspace.cleanup()

    assert not workspace.root.exists()
    assert workspace.cleanup_verified is True


def test_workspace_cleanup_failure_is_fail_closed(tmp_path: Path) -> None:
    def leave_directory(_path: Path) -> None:
        return None

    workspace = TemporaryMediaWorkspace(parent=tmp_path, remove_tree=leave_directory)
    workspace.write_bytes("capture.png", b"test")

    with pytest.raises(CleanupError):
        workspace.cleanup()

    assert workspace.cleanup_verified is False


def test_receipt_binds_payload_and_detects_tampering() -> None:
    signer = GateReceiptSigner(secret=b"s" * 32, clock=lambda: 1_000)
    binding = ReceiptBinding(
        target_id="solar-pro4",
        capability="non_vision",
        input_digest="input-digest",
        output_digest="output-digest",
        action="converted",
    )
    token = signer.sign(binding, ttl_seconds=30)

    assert signer.verify(token, expected=binding) == binding

    payload, signature = token.rsplit(".", maxsplit=1)
    tampered = f"{payload[:-1]}A.{signature}"
    with pytest.raises(ReceiptValidationError):
        signer.verify(tampered, expected=binding)

    changed_output = ReceiptBinding(
        target_id=binding.target_id,
        capability=binding.capability,
        input_digest=binding.input_digest,
        output_digest="different",
        action=binding.action,
    )
    with pytest.raises(ReceiptValidationError):
        signer.verify(token, expected=changed_output)


def test_receipt_expiry_blocks_downstream_use() -> None:
    now = [2_000]
    signer = GateReceiptSigner(secret=b"s" * 32, clock=lambda: now[0])
    binding = ReceiptBinding(
        target_id="local-text-model",
        capability="non_vision",
        input_digest="in",
        output_digest="out",
        action="passthrough",
    )
    token = signer.sign(binding, ttl_seconds=5)
    now[0] = 2_006

    with pytest.raises(ReceiptValidationError, match="expired"):
        signer.verify(token, expected=binding)
