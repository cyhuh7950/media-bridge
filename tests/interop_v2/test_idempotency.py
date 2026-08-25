import threading
import time

import pytest

from media_bridge.idempotency import IdempotencyConflict, IdempotencyStore


def test_concurrent_same_request_executes_once() -> None:
    store = IdempotencyStore(ttl_seconds=30)
    calls = 0
    lock = threading.Lock()

    def transform() -> str:
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.03)
        return "receipt"

    results: list[str] = []
    threads = [
        threading.Thread(target=lambda: results.append(store.run("k", "fp", transform)))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == 1
    assert results == ["receipt"] * 4


def test_same_key_with_different_fingerprint_is_blocked() -> None:
    store = IdempotencyStore(ttl_seconds=30)
    assert store.run("k", "fp-a", lambda: "a") == "a"
    with pytest.raises(IdempotencyConflict):
        store.run("k", "fp-b", lambda: "b")
