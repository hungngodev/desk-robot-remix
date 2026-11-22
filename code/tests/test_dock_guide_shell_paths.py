"""The dock builder commands must be executable in one terminal session."""
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs/cad/remixes/dock/README.md"


def test_dock_apriltag_block_restores_repo_root_before_seat_script():
    guide = GUIDE.read_text(encoding="utf-8")
    marker = "```sh\ncd code\nuv sync --extra vision"
    assert guide.count(marker) == 1
    tag_start = guide.index(marker) + len("```sh\n")
    tag_end = guide.index("\n```", tag_start)
    commands = guide[tag_start:tag_end].splitlines()
    assert commands[0] == "cd code"
    assert commands[-1] == "cd .."
    assert sum(line.startswith("cd ") for line in commands) == 2
    next_block = guide.index("```sh", tag_end + 4)
    next_end = guide.index("\n```", next_block + 5)
    seat_commands = guide[next_block:next_end]
    assert "python3 code/scripts/screen_dock_seat_mechanics.py" in seat_commands
    assert "cd code" not in seat_commands


def test_dock_openscad_examples_find_their_source_from_repo_root():
    guide = GUIDE.read_text(encoding="utf-8")
    command_blocks = [
        section.split("\n```", 1)[0].strip()
        for section in guide.split("```sh\n")[1:]
        if section.lstrip().startswith("openscad ")
    ]
    assert len(command_blocks) == 2
    for command, part in zip(
        command_blocks,
        ("dock_rail_entry_coupon", "dock_ir_pair_position_coupon"),
        strict=True,
    ):
        args = shlex.split(command.replace("\\\n", " "))
        assert args[0] == "openscad"
        assert args[args.index("-o") + 1] == f"{part}.stl"
        assert f'part="{part}"' in args
        assert args[-1] == "docs/cad/remixes/dock/dock_passive_fit.scad"
        assert (ROOT / args[-1]).is_file()
