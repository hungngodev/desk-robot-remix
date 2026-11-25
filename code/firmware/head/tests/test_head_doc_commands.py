"""Exercise documented shell expansion and real CLI parsing without hardware."""

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

ROOT = Path(__file__).resolve().parents[4]


class ParsedCommand(Exception):
    """Stop immediately after the real parser accepts the documented arguments."""


def parse_documented_python_command(script: str, argv: list[str], monkeypatch) -> dict:
    path = ROOT / "code" / script
    spec = importlib.util.spec_from_file_location("_documented_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_parse = argparse.ArgumentParser.parse_args
    parsed = {}

    def stop_after_parse(parser, *args, **kwargs):
        parsed.update(vars(original_parse(parser, *args, **kwargs)))
        raise ParsedCommand

    def refuse_io(*args, **kwargs):
        pytest.fail("Documented CLI parsing must not reach device or credential IO")

    with monkeypatch.context() as patch:
        patch.setattr(sys, "path", sys.path.copy())
        patch.setattr(sys, "argv", [str(path), *argv])
        spec.loader.exec_module(module)
        for name in ("robot_token_env", "read_private_env", "write_private_settings",
                     "capture_head", "preflight_private_destination", "save_wavs"):
            if hasattr(module, name):
                patch.setattr(module, name, refuse_io)
        patch.setattr(argparse.ArgumentParser, "parse_args", stop_after_parse)
        with pytest.raises(ParsedCommand):
            module.main()
    return parsed


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
    tmp_path, monkeypatch, path, needle, variable, option, expected,
):
    (tmp_path / "code").mkdir()
    # Record Python argv; suppress the separate build command entirely.
    # Never connect to a head, read credentials or start a real build.
    stub = (
        'set -e\nuv() { printf "%s\\n" "$@"; }\n'
        'python3() { printf "%s\\n" "$@"; }\n'
        'bash() { :; }\n'
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
    script = needle.split()[0]
    assert argv.count(script) == 1
    parsed = parse_documented_python_command(script, argv[argv.index(script) + 1:], monkeypatch)
    assert parsed[option[2:].replace("-", "_")] == expected
    if script == "firmware/head/private_config.py":
        assert parsed["board"] == needle.split()[-1]
        assert parsed["robot"] == "robot-01"
        assert parsed["config"] == Path("config/local.toml")
    else:
        assert parsed["robot_id"] == "robot-01"
        assert parsed["token_env"] == "DESK_ROBOT_HEAD_01_TOKEN"
        assert parsed["output_dir"] == Path("data/private/aec_lab_trial")
        assert parsed["i_consent_to_private_raw_audio"] is True

    env.pop(variable)
    result = subprocess.run(
        ["bash", "-c", command], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False, timeout=5,
    )
    assert result.returncode != 0
    assert not result.stdout
    assert variable in result.stderr
