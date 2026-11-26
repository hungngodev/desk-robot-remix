"""Keep wheel imports independent of the dev extra and host-only tools."""

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

# Distribution names that differ from their Python import names.
_DISTRIBUTIONS = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "serial": "pyserial",
    "yaml": "pyyaml",
}


def _names(requirements):
    return {
        re.match(r"[A-Za-z0-9_.-]+", requirement)[0].lower().replace("_", "-")
        for requirement in requirements
    }


def _imports(source, *, local, required, optional):
    tree = ast.parse(source)
    deferred = {
        node
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for statement in function.body
        for node in ast.walk(statement)
    }
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module.split(".")[0]]
        else:
            continue
        for module in modules:
            if module in sys.stdlib_module_names or module in local:
                continue
            distribution = _DISTRIBUTIONS.get(module, module.lower().replace("_", "-"))
            if distribution in required:
                continue
            if distribution in optional and node in deferred:
                continue
            errors.append(f"{node.lineno}: {module}")
    return errors


def test_wheel_imports_match_runtime_dependency_groups():
    code = Path(__file__).resolve().parents[1]
    project = tomllib.loads((code / "pyproject.toml").read_text())["project"]
    lock = tomllib.loads((code / "uv.lock").read_text())
    required = _names(project["dependencies"])
    extras = project["optional-dependencies"]
    optional = _names(extras["vision"] + extras["room"])
    # FastAPI exposes Starlette as its ASGI substrate. Confirm that the
    # locked FastAPI versions actually require it before allowing its imports.
    fastapi = [package for package in lock["package"] if package["name"] == "fastapi"]
    assert fastapi and "fastapi" in required
    assert all("starlette" in {dep["name"] for dep in p["dependencies"]} for p in fastapi)
    required.add("starlette")
    root = code / "laptop/src/desk_robot"
    paths = sorted(root.rglob("*.py"))
    assert root / "__init__.py" in paths
    errors = [
        f"{path.relative_to(code)}:{error}"
        for path in paths
        for error in _imports(
            path.read_text(), local={"desk_robot"}, required=required, optional=optional
        )
    ]
    assert not errors, "Undeclared or eagerly imported optional packages:\n" + "\n".join(errors)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import pytest", ["1: pytest"]),
        ("def run():\n    import aiohttp", ["2: aiohttp"]),
        ("import numpy, pytest", ["1: pytest"]),
        ("from cv2 import aruco", ["1: cv2"]),
        ("if True:\n    import serial", ["2: serial"]),
        ("def run():\n    import serial", []),
        ("async def run():\n    from cv2 import aruco", []),
        ("from . import local\nfrom PIL import Image\nimport sys", []),
        ("from missing_package import thing", ["1: missing_package"]),
    ],
)
def test_import_policy_detects_missing_and_eager_optional_dependencies(source, expected):
    assert _imports(
        source,
        local={"desk_robot"},
        required={"numpy", "pillow"},
        optional={"opencv-python", "pyserial"},
    ) == expected


@pytest.mark.parametrize("fault", ["none", "missing", "extra", "broken"])
def test_runtime_only_ci_imports_exact_source_inventory(tmp_path, fault):
    code = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load(
        (code.parent / ".github/workflows/host-verification.yml").read_text()
    )
    step = next(
        step for step in workflow["jobs"]["mac-fast"]["steps"]
        if step.get("name") == "Verify imports with locked runtime dependencies only"
    )
    assert step["working-directory"] == "code"
    assert "uv sync --no-dev --no-editable --python 3.11 --locked" in step["run"].splitlines()
    script = step["run"].split(".venv/bin/python -I - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    files = ("__init__.py", "first.py", "nested/__init__.py", "nested/second.py")
    source = tmp_path / "laptop/src/desk_robot"
    installed = tmp_path / "site/desk_robot"
    for root in (source, installed):
        for name in files:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
    if fault == "missing":
        (installed / "nested/second.py").unlink()
    elif fault == "extra":
        (installed / "stale.py").touch()
    elif fault == "broken":
        (installed / "first.py").write_text("raise RuntimeError('broken import')\n")
    result = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(installed.parent)!r})\n"
         + script],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert (result.returncode == 0) == (fault == "none"), result.stdout + result.stderr
    if fault == "none":
        assert "Imported 4 runtime modules" in result.stdout
    elif fault == "missing":
        assert "missing=['desk_robot.nested.second']" in result.stderr
    elif fault == "extra":
        assert "extra=['desk_robot.stale']" in result.stderr
    else:
        assert "broken import" in result.stderr
