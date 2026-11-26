"""Keep wheel imports independent of the dev extra and host-only tools."""

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

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
