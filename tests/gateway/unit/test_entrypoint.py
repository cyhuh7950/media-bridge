from media_bridge_gateway.entrypoints import run_gateway


def test_gateway_console_entrypoint_is_callable() -> None:
    assert callable(run_gateway)
