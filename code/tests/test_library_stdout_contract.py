"""Keep library diagnostics out of CLI JSON and detector IPC stdout."""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "laptop" / "src" / "desk_robot"

# These are protocol frames consumed by DetectorPool, not diagnostic output.
_WORKER_FRAMES = {
    "print('ready', flush=True)",
    "print(json.dumps(result, allow_nan=False), flush=True)",
}
_STDOUT_CALLS = {
    "print",
    "builtins.print",
    "sys.stdout.write",
    "sys.stdout.writelines",
    "sys.stdout.buffer.write",
    "sys.stdout.buffer.writelines",
}


def _unexpected_stdout(source: str, module: str) -> list[int]:
    tree = ast.parse(source)
    allowed: set[ast.Call] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if module == "cli.py" and node.name == "main":
            # main owns user-facing command output, including JSON.
            allowed.update(call for call in ast.walk(node) if isinstance(call, ast.Call))
        elif module == "dock_process.py" and node.name == "_worker_main":
            allowed.update(
                call for call in ast.walk(node)
                if isinstance(call, ast.Call) and ast.unparse(call) in _WORKER_FRAMES
            )
    return sorted(
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) in _STDOUT_CALLS
        and node not in allowed
    )


def test_library_modules_do_not_emit_raw_stdout():
    paths = sorted(PACKAGE.rglob("*.py"))
    assert paths, "Library source tree missing"
    violations = [
        f"{path.relative_to(PACKAGE)}:{line}"
        for path in paths
        for line in _unexpected_stdout(
            path.read_text(encoding="utf-8"), path.relative_to(PACKAGE).as_posix()
        )
    ]
    assert not violations, "Use module logging for diagnostics: " + ", ".join(violations)


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        ("api.py", "def f():\n    print('debug')", [2]),
        ("aux.py", "def f():\n    sys.stdout.write('debug')", [2]),
        ("pet.py", "builtins.print('debug')", [1]),
        ("cli.py", "def main():\n    print(result)", []),
        ("cli.py", "def helper():\n    print('debug')", [2]),
        ("dock_process.py", "def _worker_main():\n    print('ready', flush=True)", []),
        (
            "dock_process.py",
            "def _worker_main():\n    print(json.dumps(result, allow_nan=False), flush=True)",
            [],
        ),
        ("dock_process.py", "def _worker_main():\n    print('debug')", [2]),
        ("dock_process.py", "def helper():\n    print('ready', flush=True)", [2]),
        ("api.py", "logger.warning('debug')", []),
    ],
)
def test_stdout_guard_distinguishes_protocol_from_diagnostics(module, source, expected):
    assert _unexpected_stdout(source, module) == expected
