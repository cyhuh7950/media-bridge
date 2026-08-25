from datetime import UTC, datetime, timedelta

import pytest

from media_bridge.contracts_v2 import PreparedMarker
from media_bridge.interop_v2 import ReceiptValidationError, validate_cleanup_ttl


def test_result_ttl_cannot_outlive_asset_ttl() -> None:
    now = datetime.now(UTC)
    marker = PreparedMarker(
        schema_digest="sha256:" + "a" * 64,
        expires_at=now + timedelta(seconds=5),
    )
    validate_cleanup_ttl(marker, asset_expires_at=now + timedelta(seconds=10))


def test_expired_asset_blocks_result() -> None:
    now = datetime.now(UTC)
    marker = PreparedMarker(
        schema_digest="sha256:" + "a" * 64,
        expires_at=now + timedelta(seconds=20),
    )
    with pytest.raises(ReceiptValidationError):
        validate_cleanup_ttl(marker, asset_expires_at=now - timedelta(seconds=1))
