"""Exercise documented shell argument expansion without hardware or credentials."""

import os
import re
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

ROOT = Path(__file__).resolve().parents[4]


def shell_block(path: str, needle: str) -> str:
    source = (ROOT / path).read_text()
    blocks = re.findall(r"^[ \t]*```sh\n(.*?)^[ \t]*```", source, re.MULTILINE | re.DOTALL)
    matches = [dedent(block) for block in blocks if needle in block]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize(
    ("path", "needle", "variable", "option", "expected"),
    [
        (
            "code/firmware/head/sense/README.md",
            "firmware/head/private_config.py --board sense",
            "MAC_LAN_IP",
            "--server-ip",
            "192.0.2.10",
        ),
        (
            "code/firmware/head/modular/README.md",
            "firmware/head/private_config.py --board modular",
            "MAC_LAN_IP",
            "--server-ip",
            "192.0.2.10",
        ),
        (
            "docs/guides/sense-aec-port.md",
            "scripts/capture_sense_aec.py",
            "SENSE_IP",
            "--head-url",
            "http://192.0.2.10:8081",
        ),
    ],
)
def test_documented_address_is_one_argument_or_fails_closed(
    tmp_path, path, needle, variable, option, expected,
):
    (tmp_path / "code").mkdir()
    # Replace every external command in these snippets with an argv recorder.
    # Never connect to a head, read credentials or start a real build.
    stub = (
        'set -e\nuv() { printf "%s\\n" "$@"; }\n'
        'python3() { printf "%s\\n" "$@"; }\n'
        'bash() { printf "%s\\n" "$@"; }\n'
    )
    command = stub + shell_block(path, needle)
    env = dict(os.environ)
    env[variable] = "192.0.2.10"
    result = subprocess.run(
        ["bash", "-c", command], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    argv = result.stdout.splitlines()
    assert argv[argv.index(option) + 1] == expected

    env.pop(variable)
    result = subprocess.run(
        ["bash", "-c", command], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False, timeout=5,
    )
    assert result.returncode != 0
    assert not result.stdout
    assert variable in result.stderr
