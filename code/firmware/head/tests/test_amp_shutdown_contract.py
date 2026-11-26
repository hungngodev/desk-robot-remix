"""Digital output cancellation is not physical MAX98357A shutdown."""

from pathlib import Path

HEAD = Path(__file__).resolve().parents[1]
DISABLE = "Board::GetInstance().GetAudioCodec()->EnableOutput(false);"
RESET = "audio_service_.ResetDecoder();"
IDLE = "SetDeviceState(kDeviceStateIdle);"
CLOSE = "protocol_->CloseAudioChannel();"


def _section(source, start, end):
    begin = source.index(start) + len(start)
    return source[begin:source.index(end, begin)]


def _assert_order(source, *actions):
    positions = [source.index(action) for action in actions]
    assert all(left < right for left, right in zip(positions[:-1], positions[1:], strict=True))


def test_sense_amp_shutdown_gpio_is_unallocated():
    config = (HEAD / "sense/config.h").read_text()
    assert "#define AUDIO_AMP_SD_MODE_GPIO GPIO_NUM_NC" in config
    assert "static_assert(AUDIO_AMP_SD_MODE_GPIO == GPIO_NUM_NC," in config


def test_digital_disable_invalidates_aec_before_disabling_i2s():
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    method = _section(codec, "void SenseReferenceCodec::EnableOutput(bool enable) {", "\n}")
    _assert_order(
        method, "if (!enable)", "ClearReference();", "NoAudioCodec::EnableOutput(enable);",
    )


def test_urgent_flush_disables_output_before_state_handling():
    installer = (HEAD / "install_overlay.py").read_text()
    flush = _section(installer, "const bool urgent_flush =", "# BOOT privacy stop")
    _assert_order(
        flush, "if (urgent_flush)", RESET, DISABLE,
        "if (GetDeviceState() == kDeviceStateSpeaking)",
    )


def test_boot_stop_disables_output_before_channel_close_and_idle():
    installer = (HEAD / "install_overlay.py").read_text()
    stop = _section(installer, "# BOOT privacy stop", "# A physical BOOT")
    speaking = _section(stop, "} else if (state == kDeviceStateSpeaking) {", "#endif")
    _assert_order(speaking, "AbortSpeaking(kAbortReasonNone);", RESET, DISABLE, CLOSE, IDLE)


def test_privacy_stop_disables_output_before_channel_close_and_idle():
    installer = (HEAD / "install_overlay.py").read_text()
    stop = _section(installer, "// Physical BOOT has already gated PDM.", "#endif")
    _assert_order(stop, "if (state == kDeviceStateSpeaking)", RESET, DISABLE, CLOSE, IDLE)
