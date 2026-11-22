"""The selected Sense face source is distinct from measured OLED acceptance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_face_source_register_matches_selected_hsm_and_lvgl_consumer():
    source = (ROOT / "docs/source-map.md").read_text()
    decisions = (ROOT / "docs/decision-log.md").read_text()
    board = (ROOT / "code/firmware/head/sense/desk_robot_sense.cc").read_text()
    renderer = (ROOT / "code/firmware/head/overlay/face_eye_display.hpp").read_text()
    animator = (ROOT / "code/firmware/head/overlay/face_eye_animator.hpp").read_text()
    upstream = (ROOT / "code/firmware/head/overlay/stackchan_behavior.hpp").read_text()

    row = next(line for line in source.splitlines() if line.startswith("| `F023` |"))
    assert "SOURCE IMPLEMENTED; A1 PHYSICAL HOLD" in row
    assert "face_eye_animator.hpp" in row
    assert "face_eye_display.hpp" in row
    assert "Action.motion" in row
    assert "GPLv3 RoboEyes was not copied" in row
    assert "five-minute Mac-offline" in row
    assert "| `G001` |" in source
    assert "MIT behavior HSM is vendored" in source
    assert "MIT License" in upstream
    assert "const Action action = board->face_behavior_.update(obs);" in board
    assert "board->eye_animator_.Step(" in board
    assert "now_ms, action.motion," in board
    assert "board->local_eye_display_->ShowEyes(eyes);" in board
    assert "desk_robot::FaceEyeAnimator eye_animator_" in board
    assert "case Motion::kLookLeft:" in animator
    assert "blink_active_" in animator
    assert "OledDisplay::SetupUI();" in renderer
    assert "DisplayLockGuard lock(this);" in renderer
    assert "void ShowEyes(const EyeFrame& frame)" in renderer
    assert "D07 **head face engine and license**" in decisions
    assert "A1 physical HOLD remains" in decisions


def test_face_decision_preserves_hardware_gate_and_no_gpl_claim():
    source = (ROOT / "docs/source-map.md").read_text()
    decisions = (ROOT / "docs/decision-log.md").read_text()
    assert "not yet imported. Map head poses" not in source
    assert "renderer/license/0.96in-fit decision" not in source
    assert "final face selection open" not in decisions
    assert "GPLv3 RoboEyes remains reference only" in decisions
    assert "actual 128×64 overlay alignment" in decisions
    assert "20-expression coverage" in decisions
    assert "no unexpected motor action" in decisions
