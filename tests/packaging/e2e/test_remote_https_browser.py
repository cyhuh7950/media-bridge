from __future__ import annotations

import os

import pytest


def test_remote_https_browser_requires_explicit_deployment_approval() -> None:
    if os.environ.get("MEDIA_BRIDGE_REMOTE_HTTPS_APPROVED") != "1":
        pytest.skip("REMOTE_HTTPS_BROWSER_NOT_VERIFIED")
    pytest.fail("Approved remote HTTPS fixture is not configured")
