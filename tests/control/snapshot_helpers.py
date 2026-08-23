from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def private_key_pem() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def snapshot_body(*, model_id: str = "vendor/text-model") -> dict[str, object]:
    now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    return {
        "registry": {
            "version": "registry-1",
            "models": [
                {
                    "id": model_id,
                    "input_modalities": ["text"],
                    "expires_at": (now + timedelta(days=30)).isoformat(),
                    "pdf_passthrough_verified": False,
                }
            ],
        },
        "providers": [
            {
                "id": "provider-1",
                "kind": "ocr",
                "endpoint": "https://provider.test/v1/ocr",
                "secret_ref": {
                    "kind": "env",
                    "identifier": "MEDIA_BRIDGE_TEST_API_KEY",
                },
            }
        ],
        "policy": {
            "name": "default",
            "fail_closed": True,
            "max_files": 4,
            "max_media_bytes": 2_097_152,
            "max_pdf_pages": 20,
        },
    }
