from __future__ import annotations

from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter


def test_limit_is_isolated_by_credential_and_route_and_refills() -> None:
    now = 100.0
    limiter = CredentialRouteRateLimiter(
        capacity=2,
        refill_per_second=1.0,
        max_keys=10,
        idle_ttl_seconds=60,
        clock=lambda: now,
    )

    assert limiter.allow("selector-a", "/v1/responses") is True
    assert limiter.allow("selector-a", "/v1/responses") is True
    assert limiter.allow("selector-a", "/v1/responses") is False
    assert limiter.allow("selector-a", "/assets") is True
    assert limiter.allow("selector-b", "/v1/responses") is True

    now += 1.0
    assert limiter.allow("selector-a", "/v1/responses") is True


def test_bounded_memory_fails_closed_for_new_key_until_idle_entry_expires() -> None:
    now = 100.0
    limiter = CredentialRouteRateLimiter(
        capacity=1,
        refill_per_second=1.0,
        max_keys=1,
        idle_ttl_seconds=10,
        clock=lambda: now,
    )

    assert limiter.allow("selector-a", "/v1/responses") is True
    assert limiter.allow("selector-b", "/v1/responses") is False
    assert limiter.key_count == 1

    now += 11.0
    assert limiter.allow("selector-b", "/v1/responses") is True
    assert limiter.key_count == 1


def test_invalid_key_or_cost_is_denied_without_allocating_state() -> None:
    limiter = CredentialRouteRateLimiter(
        capacity=2,
        refill_per_second=1.0,
        max_keys=10,
        idle_ttl_seconds=60,
    )

    assert limiter.allow("", "/v1/responses") is False
    assert limiter.allow("selector", "not-a-route") is False
    assert limiter.allow("selector", "/v1/responses", cost=0) is False
    assert limiter.key_count == 0
