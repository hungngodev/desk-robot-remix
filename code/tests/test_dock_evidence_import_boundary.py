"""Keep read-only dock evidence independent of the motion coordinator."""

import ast
from pathlib import Path


def test_dock_evidence_uses_shared_operations_without_controller():
    path = Path(__file__).resolve().parents[1] / "laptop/src/desk_robot/dock_evidence.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "operations"
        and any(alias.name == "bounded_head_reply" for alias in node.names)
        for node in tree.body
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (
                node.module in {"controller", "desk_robot.controller"}
                or node.module in {None, "desk_robot"}
                and any(alias.name == "controller" for alias in node.names)
            )
        elif isinstance(node, ast.Import):
            assert all(alias.name != "desk_robot.controller" for alias in node.names)
