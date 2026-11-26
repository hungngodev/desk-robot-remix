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


# These standalone commands explicitly use an extra, not the wheel's base runtime.
_SCRIPT_EXTRAS = {
    "calibrate_dock_camera.py": ("vision", "opencv-python"),
    "generate_dock_tag.py": ("vision", "opencv-python"),
    "serial_bench.py": ("room", "pyserial"),
    "omni_duplex_smoke.py": ("dev", "aiohttp"),
}

# Blender supplies its own interpreter. Xiaozhi supplies core/plugins_func and
# opuslib_next (pinned upstream requirements.txt); install_overlay.py generates
# desk_robot_omni_wire. audioop is part of the server's Python 3.11 runtime.
_EXTERNAL_MODULES = {
    "scripts/render_product_concept.py": {"bpy", "mathutils"},
    "laptop/server/overlay/desk_robot_bridge.py": {"core", "plugins_func"},
    "laptop/server/overlay/desk_robot_native_omni.py": {
        "audioop", "desk_robot_omni_wire", "opuslib_next", "plugins_func",
    },
    "laptop/server/overlay/desk_robot_tools.py": {"desk_robot_omni_wire", "plugins_func"},
}


def _surface_imports(source, *, path, local, project):
    required = _names(project["dependencies"])
    extras = project["optional-dependencies"]
    if path.startswith("scripts/"):
        extra = _SCRIPT_EXTRAS.get(path.removeprefix("scripts/"))
        if extra:
            group, distribution = extra
            required |= _names(extras[group]) & {distribution}
    elif path in {
        "laptop/server/overlay/desk_robot_bridge.py",
        "laptop/server/overlay/desk_robot_native_omni.py",
    }:
        # The pinned server provides aiohttp; host overlay tests need the dev extra.
        required |= _names(extras["dev"]) & {"aiohttp"}
    return _imports(
        source,
        local=local | {"desk_robot"} | _EXTERNAL_MODULES.get(path, set()),
        required=required,
        optional=set(),
    )


def test_script_and_overlay_imports_match_dependency_owners():
    code = Path(__file__).resolve().parents[1]
    project = tomllib.loads((code / "pyproject.toml").read_text())["project"]
    errors = []
    for root in (code / "scripts", code / "laptop/server/overlay"):
        paths = sorted(root.rglob("*.py"))
        assert paths, f"No Python sources under {root}"
        for path in paths:
            relative = path.relative_to(code).as_posix()
            local = {sibling.stem for sibling in path.parent.glob("*.py")}
            errors.extend(
                f"{relative}:{error}"
                for error in _surface_imports(
                    path.read_text(), path=relative, local=local, project=project
                )
            )
    assert not errors, "Undeclared script or overlay imports:\n" + "\n".join(errors)


@pytest.mark.parametrize(
    ("path", "source", "expected"),
    [
        ("scripts/serial_bench.py", "import serial", []),
        ("scripts/generate_dock_tag.py", "import cv2", []),
        ("scripts/omni_duplex_smoke.py", "import aiohttp", []),
        ("scripts/render_product_concept.py", "import bpy, mathutils", []),
        ("scripts/render_product_concept.py", "import pytest", ["1: pytest"]),
        ("scripts/other.py", "import bpy, serial", ["1: bpy", "1: serial"]),
        ("scripts/other.py", "def run():\n    import aiohttp", ["2: aiohttp"]),
        ("scripts/other.py", "import landed_cost, httpx", []),
        ("laptop/server/overlay/desk_robot_bridge.py", "import aiohttp", []),
        ("laptop/server/overlay/desk_robot_native_omni.py", "import opuslib_next", []),
        ("laptop/server/overlay/desk_robot_tools.py", "import opuslib_next", ["1: opuslib_next"]),
        ("laptop/server/overlay/new.py", "import pytest, cv2", ["1: pytest", "1: cv2"]),
    ],
)
def test_surface_dependency_policy_is_scoped(path, source, expected):
    project = {
        "dependencies": ["httpx>=0.27"],
        "optional-dependencies": {
            "vision": ["opencv-python", "ultralytics"],
            "room": ["pyserial"],
            "dev": ["aiohttp", "pytest"],
        },
    }
    assert _surface_imports(
        source, path=path, local={"landed_cost"}, project=project
    ) == expected


@pytest.mark.parametrize(
    ("path", "group", "module"),
    [
        ("scripts/generate_dock_tag.py", "vision", "cv2"),
        ("scripts/serial_bench.py", "room", "serial"),
        ("scripts/omni_duplex_smoke.py", "dev", "aiohttp"),
        ("laptop/server/overlay/desk_robot_bridge.py", "dev", "aiohttp"),
    ],
)
def test_surface_dependency_policy_rejects_removed_extra(path, group, module):
    project = {"dependencies": [], "optional-dependencies": {group: []}}
    assert _surface_imports(
        f"import {module}", path=path, local=set(), project=project
    ) == [f"1: {module}"]


@pytest.mark.parametrize("flag", [
    "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED",
    "CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED",
])
@pytest.mark.parametrize("fault", [
    "none", "zero_header", "enabled_config", "missing_config", "duplicate_config",
    "enabled_header", "missing_header",
])
def test_default_sense_ci_audio_privacy(tmp_path, flag, fault):
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/host-verification.yml").read_text()
    )
    steps = workflow["jobs"]["sense-idf"]["steps"]
    names = [step.get("name") for step in steps]
    index = names.index("Verify default Sense audio privacy")
    assert names.index("Compile real Sense board image with local AEC") < index
    assert index < names.index("Prepare private opt-in Sense PCM compiler coverage")
    step = steps[index]
    assert step["working-directory"] == "code/firmware/head/build/xiaozhi-sense"
    assert step["shell"] == "bash"
    flags = (
        "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED",
        "CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED",
    )
    config = [f"# {key} is not set" for key in flags]
    header = ["#define CONFIG_IDF_TARGET_ESP32S3 1"]
    if fault == "enabled_config":
        config[flags.index(flag)] = f"{flag}=y"
    elif fault == "missing_config":
        config.remove(f"# {flag} is not set")
    elif fault == "duplicate_config":
        config.append(f"{flag}=y")
    elif fault == "enabled_header":
        header.append(f"#define {flag} 1")
    elif fault == "zero_header":
        header.append(f"#define {flag} 0")
    (tmp_path / "sdkconfig").write_text("\n".join(config) + "\n")
    if fault != "missing_header":
        path = tmp_path / "build/config/sdkconfig.h"
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(header) + "\n")
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    assert (result.returncode == 0) == (fault == "none"), (
        result.stdout + result.stderr
    )
