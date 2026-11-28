"""Builder guide snippets must preserve real shell arguments and safe setup refusal."""
import re
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def guide_block(guide: str, marker: str) -> str:
    text = (ROOT / "docs/guides" / guide).read_text(encoding="utf-8")
    blocks = re.findall(r"```(?:bash|sh)\n(.*?)```", text, re.DOTALL)
    matches = [block for block in blocks if marker in block]
    assert len(matches) == 1
    return matches[0]


def guide_command(guide: str, script: str) -> list[str]:
    block = guide_block(guide, script)
    lines = iter(block.splitlines())
    command = next(line for line in lines if line.startswith("uv run") and script in line)
    while command.endswith("\\"):
        assert not command.endswith("\\\\"), "Two backslashes end the shell command"
        command = command[:-1] + next(lines)
    return shlex.split(command)


def test_side_calibration_guide_preserves_both_required_arguments():
    assert guide_command(
        "side-ranging-proactive-perception.md", "scripts/calibrate_side_ranges.py",
    ) == [
        "uv", "run", "--no-sync", "python", "scripts/calibrate_side_ranges.py",
        "--robot", "robot-01", "--input", "/path/to/labeled-side-ranges.jsonl",
    ]


@pytest.mark.parametrize("guide,script,private_output", [
    ("jaw-calibration-helper.md", "scripts/calibrate_jaw_fsr.py",
     "config/local.calibration.json"),
    ("imu-handling.md", "scripts/capture_handling_trials.py",
     "config/local.handling-trials.jsonl"),
])
def test_capture_guides_use_private_coordinator_defaults(guide, script, private_output):
    args = guide_command(guide, script)
    assert args[args.index("--url") + 1] == "http://127.0.0.1:8765"
    assert args[args.index("--token-env") + 1] == "DESK_ROBOT_API_TOKEN"
    assert args[args.index("--env-file") + 1] == "config/local.env"
    assert private_output in args


@pytest.mark.parametrize("name", ["sdk-bootstrap", "esp-idf"])
@pytest.mark.parametrize("symlink", [False, True])
def test_fresh_sdk_guide_refuses_existing_paths(tmp_path, name, symlink):
    block = guide_block("build.md", "idf_commit=")
    subprocess.run(["bash", "-n"], input=block, text=True, check=True)
    code = tmp_path / "code"
    code.mkdir()
    tools = tmp_path / ".tools"
    tools.mkdir()
    path = tools / name
    if symlink:
        path.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    else:
        path.mkdir()
        (path / "preserve").write_text("existing evidence", encoding="utf-8")
    # Execute only the guard prefix; never invoke uv, git, or SDK installers in CI.
    prefix, separator, _ = block.partition("  uv venv ")
    assert separator
    result = subprocess.run(
        ["bash", "-c", prefix + "  exit 99\n)\n"],
        cwd=code, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 1
    assert "Preserve and inspect existing path" in result.stderr
    assert path.is_symlink() if symlink else (path / "preserve").is_file()
