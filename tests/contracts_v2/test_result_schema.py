import pytest
from pydantic import ValidationError

from media_bridge.contracts_v2 import (
    InteropV2Result,
    provider_call_allowed,
)


def _prepared(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": "media-bridge-interop/v2",
        "status": "PREPARED",
        "request_id": "req_123",
        "trace_id": "trace_123",
        "idempotency_key": "idem_123",
        "sanitized_messages": [{"role": "user", "content": "safe text"}],
        "original_media_removed": True,
        "asset_digests": ["sha256:" + "b" * 64],
        "media_types": ["image"],
        "transformations": [{
            "kind": "ocr", "backend": "tesseract", "version": "1",
            "input_digest": "sha256:" + "b" * 64,
            "output_digest": "sha256:" + "c" * 64,
        }],
        "backend": {"id": "ocr", "version": "1"},
        "provenance": [{
            "source": "asset_digest", "stage": "ocr",
            "evidence_digest": "sha256:" + "c" * 64,
        }],
        "confidence": {"overall": 0.9, "by_stage": {"ocr": 0.9}},
        "warnings": [],
        "information_loss": {
            "present": True, "categories": ["layout"], "summary": "layout normalized"
        },
        "required_capabilities_after": {"input_modalities": ["text"]},
        "token_estimate": {"input": 8, "method": "declared"},
        "error": None,
        "prepared_marker": {
            "schema_digest": "sha256:" + "d" * 64,
            "expires_at": "2099-08-26T00:00:00Z",
        },
    }
    value.update(overrides)
    return value


def test_prepared_requires_removal_provenance_and_transformation_digest() -> None:
    result = InteropV2Result.model_validate(_prepared())
    assert result.status == "PREPARED"
    assert result.original_media_removed is True
    assert provider_call_allowed(result)

    for invalid in (
        {"original_media_removed": False},
        {"provenance": []},
        {"transformations": []},
    ):
        with pytest.raises(ValidationError):
            InteropV2Result.model_validate(_prepared(**invalid))


def test_blocked_and_failed_never_allow_provider_call() -> None:
    for status in ("BLOCKED", "FAILED"):
        result = InteropV2Result.model_validate({
            "contract_version": "media-bridge-interop/v2",
            "status": status,
            "request_id": "req_123",
            "trace_id": "trace_123",
            "idempotency_key": "idem_123",
            "sanitized_messages": [],
            "original_media_removed": False,
            "error": {"code": "POLICY_DENIED", "message": "blocked", "retryable": False},
        })
        assert not provider_call_allowed(result)


def test_prepared_rejects_missing_provenance_in_discriminated_union() -> None:
    with pytest.raises(ValidationError):
        InteropV2Result.model_validate(_prepared(provenance=None))
