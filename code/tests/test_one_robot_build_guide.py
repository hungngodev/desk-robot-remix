"""The one complete robot builder entry stays discoverable and fail closed.

This verifies navigation and critical release language, not electrical fit.
"""
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs/guides/one-complete-robot.md"


def test_one_complete_robot_guide_is_discoverable_and_links_real_files():
    text = GUIDE.read_text(encoding="utf-8")
    assert "one-complete-robot.md" in (ROOT / "README.md").read_text()
    assert "guides/one-complete-robot.md" in (ROOT / "docs/README.md").read_text()
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("https://", "http://")):
            continue
        path = target.split("#", 1)[0]
        assert path and (GUIDE.parent / path).is_file(), target


def test_builder_guide_does_not_claim_unqualified_power_or_print_release():
    text = GUIDE.read_text()
    assert "HOLD" in text
    assert "USD 50 delivered cap" in text
    assert "including previously paid items" in text
    assert "first-robot-markdown" in text
    assert "five-pet fleet projection" in text
    assert "NOT a one-unit checkout" in text
    assert "Do not order fleet quantities" in text
    assert "only two builder facing lists" in text
    assert "pilot-cart-markdown" in text
    assert "one shared room station" in text
    assert "read-only" in text
    assert "signed net battery current" in text
    assert "86 mm" in text and "68 mm" in text
    assert "independent external motor cutoff" in text
    assert "Digital I2S acceptance does not establish acoustic playback completion" in text


def test_builder_guide_exposes_real_quiet_control_without_motion_authority():
    text = GUIDE.read_text()
    assert "POST /v1/pet/{robot_id}/quiet" in text
    assert '{"quiet": true}' in text
    assert '{"quiet": false}' in text
    assert "operator-only" in text
    assert "tool token is intentionally not authorized" in text
    assert "does not arm movement" in text


def test_both_authoritative_exits_require_physical_spatial_acceptance():
    plan = (ROOT / "docs/PLAN.md").read_text(encoding="utf-8")
    stage = plan.split("## Stage 9:", 1)[1].split("## Stage 10:", 1)[0]
    final = GUIDE.read_text(encoding="utf-8").split("## 7. Final release decision", 1)[1]
    for section in (stage, final):
        for phrase in (
            "60-object-recall-and-navigation.md#acceptance",
            "9/10 valid re-anchors",
            "at most 20 mm",
            "8/10 remembered-object returns",
            "zero false arrivals",
            "zero unsafe commands",
            "Missing or failed spatial trials prohibit duplication",
        ):
            assert phrase in section


def test_selected_builder_route_uses_explicit_full_and_private_sense_targets():
    text = GUIDE.with_name("build.md").read_text(encoding="utf-8")
    profiles = (ROOT / "code/firmware/body/platformio.ini").read_text(encoding="utf-8")
    assert "default_envs = esp32_full" in profiles
    assert "run -d firmware/body -e esp32_full --target upload" in text
    assert "logic-only upload is a prerequisite for sensor calibration" in text
    assert "motor, servo, battery and dock/charger power" in text
    assert "unexpectedly armed" in text
    selected = text.split("## Selected XIAO ESP32S3 Sense head", 1)[1].split(
        "## Modular S3 head", 1
    )[0]
    assert "private_config.py --board sense --config config/local.toml" in selected
    assert "build_head.sh --board sense --private" in selected
    assert "cd firmware/head/build/xiaozhi-sense" in selected
    assert "J3 microSD isolation" in selected
    assert "explicit operator consent" in selected
    assert "all actuator and charging power disconnected" in selected.replace("\n", " ")


def test_commissioning_and_paper_screen_fail_closed():
    build = GUIDE.with_name("build.md").read_text(encoding="utf-8")
    cad = (ROOT / "docs/cad/FUSION_ONE_ROBOT_ASSEMBLY.md").read_text(encoding="utf-8")
    measurements = (ROOT / "docs/cad/FUSION_MEASUREMENT_SHEET.md").read_text(
        encoding="utf-8"
    )
    gripper = GUIDE.with_name("first-gripper-test.md").read_text(encoding="utf-8")
    assert '${WROOM_PORT:?' in build
    assert '${SENSE_PORT:?' in build
    assert '--upload-port "$WROOM_PORT" || exit 1' in build
    assert "--inspect --samples 10" in build
    assert "issues HALT in cleanup" in build
    for flag in (
        "--floor-mount-template",
        "--floor-mount-measurements",
        "--planar-template",
        "--planar-measurements",
    ):
        assert flag in cad
    for gate in (
        "all_floor_mounts_possible_on_paper",
        "necessary_planar_coverage_on_paper",
        "necessary_stability_on_paper",
        "source_only_layout_possible",
    ):
        assert gate in cad
    assert "--template-for-dock 1" in cad
    assert "floor_mount_records[4]" in measurements
    assert "8/10 successful unassisted physical grasp-and-place trials" in GUIDE.read_text()
    assert "check_trials.py --robot robot-01 --require-pass" in gripper


def test_builder_usb_shell_blocks_fail_closed(tmp_path, monkeypatch):
    """Execute the documented shell, never the real firmware tools."""
    text = GUIDE.with_name("build.md").read_text(encoding="utf-8")
    blocks = re.findall(r"^\x60{3}sh\n(.*?)^\x60{3}\s*$", text, re.M | re.S)
    wroom = next(x for x in blocks if '--upload-port "$WROOM_PORT"' in x)
    sense = next(x for x in blocks if 'idf.py -p "$SENSE_PORT"' in x)
    inspect = next(x for x in blocks if "--inspect --samples 10" in x)
    code = tmp_path / "code"
    (code / "firmware/head/build/xiaozhi-sense").mkdir(parents=True)
    tools = tmp_path / ".tools"
    log = tmp_path / "calls"
    monkeypatch.setenv("LOG", str(log))
    monkeypatch.setenv("PATH", str(tools / "sdk-bootstrap/bin") + ":/usr/bin:/bin")
    for name in ("WROOM_PORT", "SENSE_PORT", "FAIL_UPLOAD", "FAIL_SDK"):
        monkeypatch.delenv(name, raising=False)
    for rel in ("body-pio-venv/bin/pio", "sdk-bootstrap/bin/idf.py", "sdk-bootstrap/bin/uv"):
        stub = tools / rel
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(
            '#!/bin/bash\nprintf "%s\\n" "$*" >> "$LOG"\n'
            'if [[ "$1" == run && "${FAIL_UPLOAD:-0}" == 1 ]]; then exit 13; fi\n'
        )
        stub.chmod(0o755)
    sdk = tools / "esp-idf/export.sh"
    sdk.parent.mkdir()
    sdk.write_text('return "${FAIL_SDK:-0}"\n')

    def run(script):
        if log.exists():
            log.unlink()
        result = subprocess.run(
            ["bash", "-c", script], cwd=code, capture_output=True, text=True, check=False
        )
        return result.returncode, log.read_text().splitlines() if log.exists() else []

    for script in (wroom, sense, inspect):
        assert run(script)[0] != 0
        assert not log.exists()
    monkeypatch.setenv("WROOM_PORT", "/dev/mock-body")
    monkeypatch.setenv("FAIL_UPLOAD", "1")
    status, calls = run(wroom)
    assert status != 0 and len(calls) == 1
    monkeypatch.delenv("FAIL_UPLOAD")
    assert run(wroom) == (
        0,
        [
            "run -d firmware/body -e esp32_full --target upload --upload-port /dev/mock-body",
            "device monitor --port /dev/mock-body --baud 115200",
        ],
    )
    monkeypatch.setenv("SENSE_PORT", "/dev/mock-head")
    monkeypatch.setenv("FAIL_SDK", "7")
    status, calls = run(sense)
    assert status != 0 and not calls
    monkeypatch.delenv("FAIL_SDK")
    assert run(sense) == (0, ["-p /dev/mock-head flash monitor"])
    assert run(inspect) == (
        0,
        [
            "run --no-sync python scripts/serial_bench.py "
            "--port /dev/mock-body --inspect --samples 10"
        ],
    )


def test_documented_procurement_views_execute_without_release_authority():
    """Run the exact documented read-only CLI argv, never a purchase command."""
    expected = {
        "first-robot-markdown": (
            "# First complete desk robot, one dock and one room station",
            "**PROTOTYPE BUYING STATUS: HOLD.**",
            "## 1. Reported owned or ordered",
            "## 2. First-unit remaining slots",
        ),
        "pilot-cart-markdown": (
            "# Source-locked first robot evaluation cart",
            "Historical prices are not live checkout quotes",
            "No lithium charging or motor motion is authorized.",
        ),
    }
    commands = [
        shlex.split(line) for line in GUIDE.read_text(encoding="utf-8").splitlines()
        if line.startswith("cd code && python3 scripts/procurement_release.py ")
    ]
    assert len(commands) == len(expected)
    seen = set()
    for argv in commands:
        assert argv[:6] == [
            "cd", "code", "&&", "python3", "scripts/procurement_release.py", "--format",
        ]
        assert len(argv) == 7 and argv[6] in expected
        assert argv[6] not in seen
        seen.add(argv[6])
        result = subprocess.run(
            [sys.executable, *argv[4:]], cwd=ROOT / "code",
            capture_output=True, text=True, check=False, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        for marker in expected[argv[6]]:
            assert marker in result.stdout
    assert seen == set(expected)
