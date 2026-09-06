from __future__ import annotations

import ast
from pathlib import Path


def test_local_namespace_does_not_import_enterprise_namespaces() -> None:
    root = Path(__file__).parents[2] / "media_bridge_personal"
    forbidden = {"media_bridge", "media_bridge_gateway", "media_bridge_control"}

    violations: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = None
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            if imported:
                violations.extend(
                    f"{path.name}: {name}"
                    for name in imported
                    if name.split(".", 1)[0] in forbidden
                )

    assert violations == [], (
        "Local namespace imports Enterprise namespaces: " + "; ".join(violations)
    )
