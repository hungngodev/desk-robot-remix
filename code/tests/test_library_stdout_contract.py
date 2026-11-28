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


def _resolve_dotted(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        prefix = _resolve_dotted(node.value, aliases)
        if prefix is not None:
            return f"{prefix}.{node.attr}"
    return None


def _collect_aliases(statements: list[ast.stmt], base: dict[str, str]) -> dict[str, str]:
    aliases = dict(base)
    for node in statements:
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    aliases[alias.asname or alias.name] = alias.name
            elif isinstance(child, ast.ImportFrom) and child.module:
                for alias in child.names:
                    aliases[alias.asname or alias.name] = f"{child.module}.{alias.name}"
    return aliases


def _unexpected_stdout(source: str, module: str) -> list[int]:
    tree = ast.parse(source)
    module_aliases = _collect_aliases(tree.body, {})
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
    violations: set[int] = set()
    for stmt in tree.body:
        local_aliases = (
            _collect_aliases(stmt.body, module_aliases)
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
            else module_aliases
        )
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call) or node in allowed:
                continue
            target = _resolve_dotted(node.func, local_aliases)
            if target in _STDOUT_CALLS or ast.unparse(node.func) in _STDOUT_CALLS:
                violations.add(node.lineno)
    return sorted(violations)


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
        ("aux.py", "from sys import stdout as out\ndef f():\n    out.write('debug')", [3]),
        (
            "aux.py",
            "from sys import stdout as out\ndef f():\n    out.buffer.write(b'debug')",
            [3],
        ),
        ("pet.py", "from builtins import print as emit\ndef f():\n    emit('debug')", [3]),
        ("pet.py", "import sys as s\ndef f():\n    s.stdout.writelines(['debug'])", [3]),
        ("pet.py", "import builtins as b\nb.print('debug')", [2]),
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
