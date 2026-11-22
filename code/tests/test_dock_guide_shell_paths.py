"""The dock builder commands must be executable in one terminal session."""
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
