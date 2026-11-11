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


def test_one_real_jpeg_is_attached_per_complete_audio_unit():
    wire = OmniDuplexWire()
    jpeg = b"\xff\xd8" + b"x" * 120 + b"\xff\xd9"
    for index in range(20):
        chunk = wire.append_audio(
            b"\0" * 3200, speech=index < 10,
            jpeg=jpeg, camera_age_ms=100,
        )
        assert chunk["duration_ms"] == 100
        assert chunk["audio_end_ms"] == (index + 1) * 100
        assert base64.b64decode(chunk["audio"]) == b"\0" * 3200
        assert "video_frames" in chunk if index % 10 == 9 else "video_frames" not in chunk
    assert wire.frames_sent == 2
    assert wire.commit()["response_create"] is False


def test_stale_or_fake_images_never_get_sent_to_native_model():
    wire = OmniDuplexWire()
    with pytest.raises(ValueError):
        wire.append_audio(b"\0" * 3200, speech=True,
                          jpeg=b"not-jpeg", camera_age_ms=0)
    with pytest.raises(ValueError):
        wire.append_audio(b"\0" * 3200, speech=True,
                          jpeg=b"\xff\xd8" + b"x" * 99,
                          camera_age_ms=1100)
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
