"""Keep physical handling guide commands aligned with the read-only CLI parsers."""
import argparse
import ast
import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs/guides/imu-handling.md"


def _parser(script: str) -> argparse.ArgumentParser:
    """Execute only parser declarations, never the physical capture workflow."""
    path = ROOT / "code/scripts" / script
    module = ast.parse(path.read_text(encoding="utf-8"))
    main = next(
        node for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
    )
    statements = []
    for statement in main.body:
        if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call):
            call = statement.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == "parse_args":
                break
        statements.append(statement)
    else:
        pytest.fail(f"Missing CLI parse_args in {script}")
    namespace = {"argparse": argparse, "Path": Path, "__doc__": ast.get_docstring(module)}
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(path), "exec"), namespace)
    parser = namespace["parser"]
    parser.allow_abbrev = False
    return parser


def test_handling_guide_commands_parse_and_share_trial_path():
    guide = GUIDE.read_text(encoding="utf-8")
    parsed = []
    for block in re.findall(r"```bash\n(.*?)\n```", guide, re.DOTALL):
        for command in block.replace("\\\n", " ").splitlines():
            args = shlex.split(command)
            if not args:
                continue
            script_index = args.index("python") + 1
            script = Path(args[script_index]).name
            assert script in {"capture_handling_trials.py", "calibrate_handling.py"}
            options = args[script_index + 1:]
            parsed.append((script, _parser(script).parse_args(options)))
    assert [script for script, _ in parsed] == [
        "capture_handling_trials.py", "calibrate_handling.py", "calibrate_handling.py",
    ]
    capture, paired, independent = (args for _, args in parsed)
    assert capture.url == "http://127.0.0.1:8765"
    assert capture.output == paired.jsonl
    assert independent.jsonl.suffix == ".jsonl"
