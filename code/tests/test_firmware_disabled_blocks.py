"""Keep permanently disabled scratch branches out of maintained firmware."""

import re
from pathlib import Path

import pytest

FIRMWARE = Path(__file__).resolve().parents[1] / "firmware"
SOURCE_DIRS = {"src", "include", "lib", "tests", "overlay", "sense", "modular", "waveshare"}
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp", ".ino"}
DISABLED = re.compile(
    r"^[ \t]*#[ \t]*(?:if|elif)[ \t]+(?:0|\([ \t]*0[ \t]*\))[ \t]*"
    r"(?://.*|/\*.*\*/[ \t]*)?$"
)


@pytest.mark.parametrize(
    ("line", "disabled"),
    [
        ("#if 0", True),
        ("  # if ( 0 ) // old scratch", True),
        ("#elif 0 /* obsolete */", True),
        ("#ifdef DESK_ROBOT_STEPPER", False),
        ("#if !DESK_ROBOT_STEPPER", False),
        ("#if 0 || FEATURE", False),
        ("#if FEATURE == 0", False),
        ("// #if 0", False),
        ('const char* text = "#if 0";', False),
    ],
)
def test_literal_disabled_directive_pattern(line, disabled):
    assert bool(DISABLED.fullmatch(line)) is disabled


def test_firmware_has_no_literal_disabled_branches():
    # Restrict the scan to maintained source trees, not downloaded SDKs or build output.
    paths = sorted(
        path
        for directory in FIRMWARE.glob("*/*")
        if directory.is_dir() and directory.name in SOURCE_DIRS
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    )
    assert paths, "firmware source files are missing"
    disabled = [
        f"{path.relative_to(FIRMWARE)}:{number}"
        for path in paths
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if DISABLED.fullmatch(line)
    ]
    assert not disabled, "Remove literal disabled branches:\n" + "\n".join(disabled)
