"""Native full-duplex audio/video protocol regression, no invented hardware."""
import base64

import pytest

from desk_robot.realtime_omni_protocol import OmniDuplexWire


def delta(response_id="r1", epoch=0, pcm=None):
    pcm = pcm if pcm is not None else b"\0" * 4800  # 100ms mono 24k PCM16
    return {
        "type": "response.output_audio.delta", "response_id": response_id,
        "format": "pcm16", "sample_rate_hz": 24000,
        "delta": base64.b64encode(pcm).decode("ascii"),
        "metadata": {"epoch": epoch},
    }


def test_native_open_session_uses_pcm_and_truthful_playback_policy():
    wire = OmniDuplexWire()
    session = wire.session_update()
    assert session["type"] == "session.update"
    assert session["session"]["model"] == "openbmb/MiniCPM-o-4_5"
    assert session["session"]["playback_commit_policy"] == "ack_only"
    assert session["session"]["overlap_policy"] == "listen_only"
    assert session["session"]["input_audio_format"] == "pcm16"


def test_distinct_real_camera_receipts_only_on_complete_one_second_model_units():
    wire = OmniDuplexWire()
    jpeg = b"\xff\xd8" + b"x" * 120 + b"\xff\xd9"
    for index in range(20):
        # Unlike Gemini Live's independent video messages, this pinned
        # model only accepts a camera image on an append closing 1s of audio.
        # A new receipt can be offered again until that exact boundary.
        receipt = 101 if index < 10 else 102
        chunk = wire.append_audio(
            b"\0" * 3200, speech=index < 10,
            jpeg=jpeg, camera_age_ms=100, frame_receipt_us=receipt,
        )
        assert chunk["duration_ms"] == 100
        assert chunk["audio_end_ms"] == (index + 1) * 100
        assert base64.b64decode(chunk["audio"]) == b"\0" * 3200
        assert ("video_frames" in chunk) == (index in (9, 19))
    assert wire.frames_sent == 2
    assert wire.commit()["response_create"] is False


def test_partial_unit_never_falsely_claims_that_the_native_model_saw_a_frame():
    wire = OmniDuplexWire()
    jpeg = b"\xff\xd8" + b"frame" * 12 + b"\xff\xd9"
    first = wire.append_audio(b"\0" * 3200, speech=True)
    assert "video_frames" not in first
    short = wire.append_audio(
        b"\0" * 3200, speech=True,
        jpeg=jpeg, camera_age_ms=20, frame_receipt_us=3001,
    )
    assert "video_frames" not in short
    repeated = wire.append_audio(
        b"\0" * 3200, speech=False,
        jpeg=jpeg, camera_age_ms=40, frame_receipt_us=3001,
    )
    assert "video_frames" not in repeated
    assert wire.frames_sent == 0


def test_never_send_native_video_without_a_real_mac_receipt_or_recent_human_speech():
    wire = OmniDuplexWire()
    jpeg = b"\xff\xd8" + b"frame" * 12 + b"\xff\xd9"
    with pytest.raises(ValueError):
        wire.append_audio(
            b"\0" * 3200, speech=True, jpeg=jpeg, camera_age_ms=1,
        )
    idle = wire.append_audio(
        b"\0" * 3200, speech=False,
        jpeg=jpeg, camera_age_ms=1, frame_receipt_us=5001,
    )
    assert "video_frames" not in idle
    assert wire.frames_sent == 0




def test_recent_speech_tail_can_pair_actual_frame_with_completed_native_model_unit():
    wire = OmniDuplexWire()
    jpeg = b"\xff\xd8" + b"frame" * 12 + b"\xff\xd9"
    # Speech ends at 700ms, but the model's first one-second audio unit
    # closes during a real trailing silent audio chunk. The XIAO frame is
    # included only there and never repeated on a later unit.
    for _ in range(7):
        packet = wire.append_audio(b"\0" * 3200, speech=True)
        assert "video_frames" not in packet
    for index in range(13):
        packet = wire.append_audio(
            b"\0" * 3200, speech=False, jpeg=jpeg,
            camera_age_ms=100, frame_receipt_us=43001,
        )
        assert ("video_frames" in packet) == (index == 2)
    assert wire.frames_sent == 1


def test_barge_in_drops_obsolete_visual_tail_until_new_authentic_speech():
    wire = OmniDuplexWire()
    jpeg = b"\xff\xd8" + b"x" * 20 + b"\xff\xd9"
    for _ in range(9):
        wire.append_audio(b"\0" * 3200, speech=True)
    wire.interrupt()
    # The next packet closes the abandoned previous 1s unit, but it is
    # silence after an interruption, NOT a new visual question.
    dropped = wire.append_audio(
        b"\0" * 3200, speech=False, jpeg=jpeg,
        camera_age_ms=0, frame_receipt_us=10,
    )
    assert "video_frames" not in dropped
    for _ in range(9):
        wire.append_audio(b"\0" * 3200, speech=True)
    fresh = wire.append_audio(
        b"\0" * 3200, speech=True, jpeg=jpeg,
        camera_age_ms=20, frame_receipt_us=11,
    )
    assert base64.b64decode(fresh["video_frames"][0]) == jpeg
    assert wire.frames_sent == 1


def test_stale_or_fake_images_never_get_sent_to_native_model():
    wire = OmniDuplexWire()
    with pytest.raises(ValueError):
        wire.append_audio(b"\0" * 3200, speech=True,
                          jpeg=b"not-jpeg", camera_age_ms=0)
    with pytest.raises(ValueError):
        wire.append_audio(b"\0" * 3200, speech=True,
                          jpeg=b"\xff\xd8" + b"x" * 99,
                          camera_age_ms=1100)
    # A correctly aged source image must still have a genuine JPEG EOI.
    with pytest.raises(ValueError, match="JPEG"):
        wire.append_audio(
            b"\0" * 3200, speech=True,
            jpeg=b"\xff\xd8" + b"x" * 99,
            camera_age_ms=100, frame_receipt_us=43,
        )
    # A complete JPEG at a valid source receipt is accepted for buffering.
    complete = wire.append_audio(
        b"\0" * 3200, speech=True,
        jpeg=b"\xff\xd8" + b"x" * 99 + b"\xff\xd9",
        camera_age_ms=100, frame_receipt_us=44,
    )
    assert complete["audio_end_ms"] > 0

    with pytest.raises(ValueError):
        wire.append_audio(b"\0" * 123, speech=True)
    with pytest.raises(ValueError):
        wire.append_audio(b"\0" * 3200, speech="yes")


def test_real_generated_pcm_is_not_automatically_acknowledged():
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "r1",
        "response": {"id": "r1", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    packet = wire.handle_event(delta())
    assert packet is not None and packet.pcm24k == b"\0" * 4800
    assert packet.total_generated_ms == 100
    assert wire.played_ms == 0
    assert wire.generated_bytes == 4800
    with pytest.raises(ValueError):
        wire.playback_ack(response_id="r1", actually_played_ms=101)
    with pytest.raises(ValueError):
        wire.playback_ack(response_id="different", actually_played_ms=70)
    assert wire.playback_ack(
        response_id="r1", actually_played_ms=70,
    ) == {
        "type": "playback.ack", "response_id": "r1",
        "played_ms": 70, "committed_ms": 70, "truncate": False,
    }
    with pytest.raises(ValueError):
        wire.playback_ack(response_id="r1", actually_played_ms=69)
    assert wire.played_ms == 70


def test_interrupt_ignores_old_response_until_new_pcm_committed():
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "old",
        "response": {"id": "old", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    assert wire.handle_event(delta("old")) is not None
    messages = wire.interrupt()
    assert [m["type"] for m in messages] == [
        "response.cancel", "output_audio_buffer.clear",
    ]
    assert wire.handle_event(delta("old")) is None
    wire.handle_event({
        "type": "response.created", "response_id": "old_late",
        "response": {"id": "old_late", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    assert wire.handle_event(delta("old_late")) is None
    wire.append_audio(b"\0" * 3200, speech=True)
    wire.commit()
    wire.handle_event({
        "type": "response.created", "response_id": "very_old",
        "response": {"id": "very_old", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    assert wire.handle_event(delta("very_old")) is None
    wire.handle_event({
        "type": "response.created", "response_id": "new",
        "response": {"id": "new", "metadata": {"duplex_event": {"epoch": 2}}},
    })
    assert wire.handle_event(delta("old")) is None
    assert wire.handle_event(delta("new", epoch=2)) is not None
    # Old response.done must not silence the new response.
    wire.handle_event({"type": "response.done", "response_id": "old"})
    assert wire.handle_event(delta("new", epoch=2)) is not None
    wire.handle_event({"type": "response.done", "response_id": "new"})
    assert wire.handle_event(delta("new", epoch=2)) is None


def test_backend_audio_fails_closed_on_wrong_format_and_bad_base64():
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "r1",
        "response": {"id": "r1"},
    })
    bad = delta()
    bad["format"] = "opus"
    with pytest.raises(ValueError, match="codec"):
        wire.handle_event(bad)
    bad = delta()
    bad["delta"] = "!"
    with pytest.raises(ValueError, match="base64"):
        wire.handle_event(bad)
    with pytest.raises(RuntimeError):
        wire.handle_event({"type": "error", "error": {"code": "backend_failed"}})


@pytest.mark.parametrize("mutation", [
    ("type", "session.error"),
    ("model", "other/model"),
    ("implementation_level", "turn_based"),
    ("supports_barge_in", False),
    ("supports_input_append", False),
    ("chunk_period_ms", 100),
    ("input_audio_format", "opus"),
    ("output_audio_format", "opus"),
    ("input_rate", 24000),
    ("output_rate", 16000),
    ("output_format_type", "audio/mulaw"),
])
def test_shared_native_model_handshake_rejects_fake_duplex_claims(mutation):
    """Smoke probe and live Xiaozhi route must reject identical fake backends."""
    from desk_robot.realtime_omni_protocol import verify_native_server

    selected = "openbmb/MiniCPM-o-4_5"
    valid = {
        "type": "session.created",
        "session": {
            "model": selected,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "capabilities": {
                "implementation_level": "model_native_duplex",
                "supports_input_append": True,
                "supports_barge_in": True,
                "chunk_period_ms": 1000,
            },
            "audio": {
                "input": {"sample_rate_hz": 16000},
                "output": {"format": {"type": "audio/pcm", "rate": 24000}},
            },
        },
    }
    assert verify_native_server(valid, selected) is None
    name, value = mutation
    if name == "type":
        valid["type"] = value
    elif name == "model":
        valid["session"]["model"] = value
    elif name == "input_rate":
        valid["session"]["audio"]["input"]["sample_rate_hz"] = value
    elif name == "output_rate":
        valid["session"]["audio"]["output"]["format"]["rate"] = value
    elif name == "output_format_type":
        valid["session"]["audio"]["output"]["format"]["type"] = value
    elif name in ("input_audio_format", "output_audio_format"):
        valid["session"][name] = value
    else:
        valid["session"]["capabilities"][name] = value
    with pytest.raises(RuntimeError):
        verify_native_server(valid, selected)
