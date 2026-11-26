"""The one complete robot builder entry stays discoverable and fail closed.

This verifies navigation and critical release language, not electrical fit.
"""
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

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
        if argv[6] == "pilot-cart-markdown":
            source_rows = _pilot_quote_contract()
            _assert_pilot_sku_rows(result.stdout, source_rows)
            for sku in sorted(_PILOT_SKUS):
                mutant = "\n".join(
                    line for line in result.stdout.splitlines()
                    if not (line.startswith("|") and f"| {sku} |" in line)
                )
                with pytest.raises(AssertionError):
                    _assert_pilot_sku_rows(mutant + "\n" + sku, source_rows)
            _assert_pilot_quote_mutations(result.stdout, source_rows)
    assert seen == set(expected)


_PILOT_SKUS = {
    "SEN-19-006", "COM-05-067", "SEN-25-020", "SEN-24-027", "COM-05-045",
    "COM-05-093", "DFR0954", "D2F-01L3", "CS20-02P110-04-1X", "2873",
    "BOB-13282", "TSOP38438", "TSAL6200",
}


def _pilot_quote_contract():
    import ast

    source = (ROOT / "code/scripts/procurement_release.py").read_text(encoding="utf-8")
    tables = [
        node.value for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PILOT_SAMPLE_PRODUCTS"
                for target in node.targets)
    ]
    assert len(tables) == 1
    expected = {
        item[2]: (str(item[4]), item[3]) for item in ast.literal_eval(tables[0]).values()
    }
    assert set(expected) == _PILOT_SKUS
    return expected


def _assert_pilot_sku_rows(markdown, expected):
    header = "| Candidate checkout seller | Brand or manufacturer | SKU |"
    lines = markdown.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(header)]
    assert len(starts) == 1, "Missing or duplicate pilot table header"
    rows = {}
    for line in lines[starts[0] + 2:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 9, line
        assert cells[2] not in rows, cells[2]
        rows[cells[2]] = (cells[4], cells[6])
    assert rows == expected


def _assert_pilot_quote_mutations(markdown, expected):
    lines = markdown.splitlines()
    row = next(line for line in lines if "| COM-05-067 |" in line)
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    for column, invalid in ((4, "1"), (6, "https://example.invalid/wrong-board")):
        mutated = cells.copy()
        mutated[column] = invalid
        mutant = markdown.replace(row, "| " + " | ".join(mutated) + " |", 1)
        with pytest.raises(AssertionError):
            _assert_pilot_sku_rows(mutant, expected)


_SAFETY_MARKERS = (
    ("3. Wiring starts unpowered and with independent safety",
     "0x70 and 0x71 mux lanes must be isolated and verified at 3.3 V"),
    ("4. Build and inspect code without energizing a robot",
     "3.3 V probe output and analog A0"),
    ("4. Build and inspect code without energizing a robot", "3.3 V UART"),
    ("7. Final release decision",
     "Final parts printing, full buying release, loaded desk movement, "
     "battery charging and autonomous docking remain HOLD until the named receipts exist."),
)
_DC_MARKERS = (
    "LOW/LOW (coast, high impedance) from HIGH/HIGH (active brake)",
    "must be zero on STOP; neither coast nor nSLEEP LOW proves zero wheel speed.",
    "No active-brake substitution is qualified. Measure loaded coast distance.",
)


def _assert_builder_safety_markers(guide, dc_guide):
    for heading, marker in _SAFETY_MARKERS:
        section = guide.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
        assert marker in " ".join(section.split()), heading
    dc = " ".join(dc_guide.split())
    for marker in _DC_MARKERS:
        assert marker in dc, marker


def test_builder_safety_warnings_are_scoped_and_mutation_sensitive():
    guide = GUIDE.read_text(encoding="utf-8")
    dc = (ROOT / "docs/hardware/dc-motor-independent-watchdog.md").read_text(
        encoding="utf-8"
    )
    _assert_builder_safety_markers(guide, dc)
    for _, marker in _SAFETY_MARKERS:
        with pytest.raises(AssertionError):
            _assert_builder_safety_markers(guide.replace(marker, "", 1), dc)
    for marker in _DC_MARKERS:
        with pytest.raises(AssertionError):
            _assert_builder_safety_markers(guide, " ".join(dc.split()).replace(marker, "", 1))
