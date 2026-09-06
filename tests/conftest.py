from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    root = Path(str(config.rootpath))
    for item in items:
        path = Path(str(item.fspath))
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if "integration" in relative_parts:
            item.add_marker(pytest.mark.integration)
        if {"postgres_url", "clean_postgres", "migrated_postgres"}.intersection(
            item.fixturenames
        ):
            item.add_marker(pytest.mark.integration)
