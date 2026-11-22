"""The physical BOOT mute must run on press, not after release.

Source contracts are not a substitute for the actual on-head held-button PCM
and Opus leakage test. Xiaozhi's pinned OnClick event follows release.
"""
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "sense" / "desk_robot_sense.cc"


def _callbacks():
    source = SOURCE.read_text()
    assert "std::atomic<bool> boot_press_muted_{false};" in source
    assert "boot_button_.OnPressDown([this]() {" in source
    press = source.split("boot_button_.OnPressDown([this]() {", 1)[1].split(
        "boot_button_.OnClick([this]() {", 1
    )[0]
    click = source.split("boot_button_.OnClick([this]() {", 1)[1].split(
        "void StartNetwork() override", 1
    )[0]
    return press, click


def test_boot_press_gates_real_pdm_and_opus_before_release_or_network_abort():
    press, _ = _callbacks()
    expected = (
        "audio_operator_touched_.store(true, std::memory_order_release);",
        "audio_operator_muted_.exchange(",
        "boot_press_muted_.store(!already_muted, std::memory_order_release);",
        "app.SetSenseMicrophonePrivacyMuted(true);",
        "->SetMicrophonePrivacyMuted(true);",
        "app.StopListening();",
    )
    for phrase in expected:
        assert phrase in press
    assert press.index(expected[0]) < press.index(expected[1])
    assert press.index(expected[3]) < press.index(expected[4])
    assert press.index(expected[4]) < press.index(expected[5])


def test_boot_release_does_not_reverse_press_mute_and_second_tap_can_unmute():
    press, click = _callbacks()
    assert "if (already_muted) return;" in press
    assert "boot_press_muted_.exchange(false, std::memory_order_acq_rel)" in click
    assert click.index("boot_press_muted_.exchange(false") < click.index(
        "const bool now_muted = !audio_operator_muted_.load("
    )
    assert "app.SetSenseMicrophonePrivacyMuted(now_muted);" in click
    assert "->SetMicrophonePrivacyMuted(now_muted);" in click
    assert "if (state == kDeviceStateIdle) app.ToggleChatState();" in click
    assert "if (state == kDeviceStateStarting)" in click
    assert click.index("if (state == kDeviceStateStarting)") < click.index(
        "boot_press_muted_.exchange(false"
    )


def test_boot_long_hold_is_privacy_action_even_without_click_or_long_press():
    press, click = _callbacks()
    assert "app.StopListening();" in press
    assert "OnLongPress" not in press
    assert "if (boot_press_muted_.exchange(false" in click
