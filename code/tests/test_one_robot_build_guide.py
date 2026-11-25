"""The one complete robot builder entry stays discoverable and fail closed.

This verifies navigation and critical release language, not electrical fit.
"""
import re
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
    assert "only two builder facing lists" in text
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
    ):
        assert gate in cad
    assert "floor_mount_records[4]" in measurements
    assert "check_trials.py --robot robot-01 --require-pass" in gripper
