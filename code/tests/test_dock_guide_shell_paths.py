"""The dock builder commands must be executable in one terminal session."""

import posixpath
import re
import shlex
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

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
    logical = []
    cur = ""
    for line in commands:
        if cur:
            cur = f"{cur} {line.rstrip(chr(92)).strip()}"
        else:
            cur = line.rstrip(chr(92)).strip()
        if not line.endswith("\\"):
            logical.append(shlex.split(cur))
            cur = ""
    tag_cmds = [c for c in logical if "scripts/generate_dock_tag.py" in c]
    assert len(tag_cmds) == 2
    assert any("--verify" in c for c in tag_cmds)
    assert all((ROOT / "code/scripts/generate_dock_tag.py").is_file() for _c in tag_cmds)
    next_block = guide.index("```sh", tag_end + 4)
    next_end = guide.index("\n```", next_block + 5)
    seat_commands = guide[next_block + 5:next_end].strip()
    assert "python3 code/scripts/screen_dock_seat_mechanics.py" in seat_commands
    assert "cd code" not in seat_commands
    seat_args = shlex.split(seat_commands.replace("\\\n", " "))
    assert (ROOT / seat_args[seat_args.index("python3") + 1]).is_file()
    if "--template-for-dock" in seat_args:
        dock_idx = int(seat_args[seat_args.index("--template-for-dock") + 1])
        assert 1 <= dock_idx <= 5


def test_dock_openscad_examples_find_their_source_from_repo_root(tmp_path):
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
        assert "--export-format" in args and args[args.index("--export-format") + 1] == "binstl"
        assert args[args.index("-o") + 1] == f"{part}.stl"
        assert f'part="{part}"' in args
        assert args[-1] == "docs/cad/remixes/dock/dock_passive_fit.scad"
        assert (ROOT / args[-1]).is_file()
        if __import__("shutil").which("openscad") is not None:
            out_stl = tmp_path / f"{part}.stl"
            subprocess.run(
                [args[0], "--export-format", "binstl", "-o", str(out_stl),
                 "-D", f'part="{part}"', str(ROOT / args[-1])],
                check=True, capture_output=True, text=True, timeout=60,
            )
            assert out_stl.stat().st_size > 84


def _assert_tracked_links(guide, contents, tracked, required):
    """Resolve inline file links relative to the guide, not the shell cwd."""
    resolved = set()
    for destination in re.findall(r"\]\(([^)\s]+)\)", contents):
        link = urlsplit(destination)
        if link.scheme or link.netloc or not link.path:
            continue
        path = posixpath.normpath(posixpath.join(posixpath.dirname(guide), unquote(link.path)))
        assert path in tracked, f"{guide}: untracked or missing link {destination} -> {path}"
        resolved.add(path)
    assert required <= resolved, f"{guide}: missing CAD links {sorted(required - resolved)}"


@pytest.mark.parametrize(
    ("guide", "required"),
    [
        (
            "docs/cad/FUSION_ONE_ROBOT_ASSEMBLY.md",
            {
                "originals/smars-stepper/SMARS_2BJY8-Chassis.stl",
                "originals/smars-stepper/SMARS_28BYJ-48-RearWheel.stl",
                "originals/smars/mechanical_track.stl",
                "originals/smars/slave_wheel_SL.stl",
                "originals/forklift/fork_lift_e.stl",
                "originals/forklift/fork_lift_f.stl",
                "originals/gripper/servo_case_arm.stl",
                "originals/gripper/arm_rack.stl",
                "originals/gripper/pinion_gear.stl",
                "originals/sparky-head/sparky_shell.stl",
                "originals/sparky-head/sparky_collar.stl",
                "originals/sparky-head/sparky_lid.stl",
                "remixes/mg90s_pocket_fit_gauges.scad",
                "remixes/costume_keepouts.scad",
                "remixes/dock/dock_passive_fit.scad",
                "FUSION_MEASUREMENT_SHEET.md",
            },
        ),
        (
            "docs/cad/remixes/dock/README.md",
            {
                "remixes/dock/dock_passive_fit.scad",
                "remixes/remaining_fit_gauges.scad",
                "remixes/one_robot_adapter_kit_README.md",
                "FUSION_ONE_ROBOT_ASSEMBLY.md",
                "FUSION_MEASUREMENT_SHEET.md",
            },
        ),
    ],
)
def test_cad_guide_links_resolve_to_tracked_files(guide, required):
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=ROOT)
    tracked = {
        path.decode("utf-8")
        for entry in entries.split(b"\0") if entry
        for metadata, path in [entry.split(b"\t", 1)]
        if metadata.split()[0] in {b"100644", b"100755"} and metadata.split()[2] == b"0"
    }
    _assert_tracked_links(
        guide,
        (ROOT / guide).read_text(encoding="utf-8"),
        tracked,
        {f"docs/cad/{path}" for path in required},
    )


@pytest.mark.parametrize("bad_link", ["missing.scad", "MODEL.scad", "../model.scad", ""])
def test_cad_guide_link_contract_rejects_drift(bad_link):
    guide = "docs/cad/remixes/dock/README.md"
    target = "docs/cad/remixes/dock/model.scad"
    contents = "[CAD](model.scad#part) [upstream](https://example.com/model.scad)"
    _assert_tracked_links(guide, contents, {target}, {target})
    changed = contents.replace("model.scad#part", bad_link)
    with pytest.raises(AssertionError, match="untracked or missing link|missing CAD links"):
        _assert_tracked_links(guide, changed, {target}, {target})
