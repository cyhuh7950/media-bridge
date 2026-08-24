from media_bridge_control.test_lab import AdminActionRateLimiter


def test_admin_action_rate_limiter_is_bounded_per_key_and_window() -> None:
    clock = [10.0]
    limiter = AdminActionRateLimiter(
        capacity=1,
        window_seconds=5,
        max_keys=2,
        monotonic=lambda: clock[0],
    )

    assert limiter.allow("admin:preview") is True
    assert limiter.allow("admin:preview") is False
    assert limiter.allow("operator:preview") is True
    clock[0] = 16.0
    assert limiter.allow("admin:preview") is True
