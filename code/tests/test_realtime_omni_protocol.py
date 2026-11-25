"""Native full-duplex audio/video protocol regression, no invented hardware."""
import base64

import pytest
from desk_robot.realtime_omni_protocol import I2sTransmissionPrefix, OmniDuplexWire


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


def test_proactive_native_video_continues_during_quiet_room_audio():
    wire = OmniDuplexWire()
    jpeg = b"\xff\xd8" + b"frame" * 12 + b"\xff\xd9"
    with pytest.raises(ValueError):
        wire.append_audio(
            b"\0" * 3200, speech=True, jpeg=jpeg, camera_age_ms=1,
        )
    for _ in range(9):
        idle = wire.append_audio(
            b"\0" * 3200, speech=False,
            jpeg=jpeg, camera_age_ms=1, frame_receipt_us=5001,
        )
        assert "video_frames" not in idle
    idle = wire.append_audio(
        b"\0" * 3200, speech=False,
        jpeg=jpeg, camera_age_ms=1, frame_receipt_us=5001,
    )
    assert base64.b64decode(idle["video_frames"][0]) == jpeg
    assert wire.frames_sent == 1
    # An unchanged frame is not another new visual observation.
    for _ in range(10):
        result = wire.append_audio(
            b"\0" * 3200, speech=False,
            jpeg=jpeg, camera_age_ms=1, frame_receipt_us=5001,
        )
        assert "video_frames" not in result




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


def test_proactive_quiet_audio_rearms_after_barge_without_new_human_speech():
    wire = OmniDuplexWire()
    jpeg = b"\xff\xd8" + b"silent-room-video" + b"\xff\xd9"
    wire.interrupt()
    assert wire._needs_new_input
    for index in range(10):
        packet = wire.append_audio(
            b"\0" * 3200, speech=False,
            jpeg=jpeg, camera_age_ms=10, frame_receipt_us=61001,
        )
        if index < 9:
            assert "video_frames" not in packet
            assert wire._needs_new_input
    assert "video_frames" in packet
    assert not wire._needs_new_input
    assert wire.frames_sent == 1
    wire.handle_event({
        "type": "response.created",
        "response_id": "quiet_proactive_new",
        "response": {"metadata": {"duplex_event": {"epoch": 2}}},
    })
    assert wire.response_id == "quiet_proactive_new"
    assert wire.accept_output


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
        wire.playback_ack(response_id="r1", actually_played_ms=0)
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
    with pytest.raises(ValueError):
        wire.playback_ack(response_id="r1", actually_played_ms=70)
    # Speaker may finish draining queued audio after model generation ends.
    wire.handle_event({"type": "response.done", "response_id": "r1"})
    assert wire.playback_ack(response_id="r1", actually_played_ms=100)[
        "played_ms"
    ] == 100
    with pytest.raises(ValueError):
        wire.playback_ack(response_id="r1", actually_played_ms=100)
    assert wire.played_ms == 100


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


def test_double_cancel_epoch_floor_rejects_older_model_audio_even_after_recovery():
    """Upstream response.cancel and output clear EACH advance epoch once."""
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "before",
        "response": {"id": "before", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    wire.interrupt()
    assert wire._min_server_epoch == 2
    wire.append_audio(bytes(3200), speech=True)
    wire.commit()
    wire.handle_event({
        "type": "response.created", "response_id": "stale-plus-one",
        "response": {"id": "stale-plus-one",
                     "metadata": {"duplex_event": {"epoch": 1}}},
    })
    assert wire.response_id is None
    wire.handle_event({
        "type": "response.created", "response_id": "current",
        "response": {"id": "current", "metadata": {"duplex_event": {"epoch": 2}}},
    })
    assert wire.handle_event(delta("current", epoch=2)) is not None
    # This used to become active after _interrupted was reset by "current".
    wire.handle_event({
        "type": "response.created", "response_id": "reordered-old",
        "response": {"id": "reordered-old",
                     "metadata": {"duplex_event": {"epoch": 1}}},
    })
    assert wire.response_id == "current"
    assert wire.handle_event(delta("current", epoch=2)) is not None


def test_two_rapid_native_barges_fence_four_server_epoch_advances():
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "old",
        "response": {"id": "old", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    wire.interrupt()
    wire.interrupt()
    assert wire._min_server_epoch == 4
    wire.append_audio(bytes(3200), speech=True)
    wire.commit()
    wire.handle_event({
        "type": "response.created", "response_id": "too-early",
        "response": {"id": "too-early",
                     "metadata": {"duplex_event": {"epoch": 3}}},
    })
    assert wire.response_id is None
    wire.handle_event({
        "type": "response.created", "response_id": "new",
        "response": {"id": "new", "metadata": {"duplex_event": {"epoch": 4}}},
    })
    assert wire.handle_event(delta("new", epoch=4)) is not None


def test_native_handshake_can_reset_local_preconnect_interrupt_but_not_repeat():
    wire = OmniDuplexWire()
    wire.interrupt()
    assert wire._min_server_epoch == 2
    greeting = {"type": "session.created", "session": {"epoch": 40}}
    wire.handle_event(greeting)
    assert wire._min_server_epoch is None
    assert wire._server_epoch_seen == 40
    wire.handle_event({
        "type": "response.created", "response_id": "fresh",
        "response": {"id": "fresh", "metadata": {"duplex_event": {"epoch": 40}}},
    })
    assert wire.handle_event(delta("fresh", epoch=40)) is not None
    with pytest.raises(ValueError, match="Duplicate"):
        wire.handle_event(greeting)
    with pytest.raises(ValueError, match="epoch"):
        OmniDuplexWire().handle_event({
            "type": "session.created", "session": {"epoch": -1},
        })


def test_epochless_old_response_cannot_override_recovered_native_output():
    """After a native STOP, missing epoch must never become speaker authority."""
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "before",
        "response": {"id": "before", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    wire.interrupt()
    wire.append_audio(bytes(3200), speech=True)
    wire.commit()
    wire.handle_event({
        "type": "response.created", "response_id": "recovered",
        "response": {"id": "recovered", "metadata": {"duplex_event": {"epoch": 2}}},
    })
    assert wire.response_id == "recovered"
    assert wire.handle_event(delta("recovered", epoch=2)) is not None
    for ambiguous in (
        {"type": "response.created", "response_id": "old-no-epoch"},
        {"type": "response.created", "response_id": "old-no-metadata",
         "response": {"id": "old-no-metadata"}},
        {"type": "response.created", "response_id": "old-empty-metadata",
         "response": {"id": "old-empty-metadata", "metadata": {}}},
    ):
        wire.handle_event(ambiguous)
        assert wire.response_id == "recovered"
        assert wire.handle_event(delta("recovered", epoch=2)) is not None


def test_epochless_native_response_allowed_before_first_barge_for_legacy_fixture():
    """Preserve simple pre-interruption simulated transport tests only."""
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "first",
        "response": {"id": "first"},
    })
    assert wire.handle_event(delta("first")) is not None


def test_native_listen_epoch_rejects_stale_silence_after_interrupt():
    wire = OmniDuplexWire()
    assert wire.model_listen_current({
        "type": "response.listen", "epoch": 0,
    })
    wire.interrupt()
    assert not wire.model_listen_current({
        "type": "response.listen", "epoch": 0,
    })
    assert not wire.model_listen_current({
        "type": "response.listen", "epoch": 2,
    })  # Need fresh microphone PCM or an explicit commit.
    wire.append_audio(bytes(3200), speech=False)
    wire.commit()
    assert wire.model_listen_current({
        "type": "response.listen", "epoch": 2,
    })
    assert not wire.model_listen_current({
        "type": "response.listen", "epoch": 1,
    })
    assert not wire.model_listen_current({
        "type": "response.listen", "epoch": "2",
    })
    assert not wire.model_listen_current({
        "type": "response.listen",
    })
    assert not wire.model_listen_current({
        "type": "response.listen", "epoch": 2, "response_id": "unknown",
    })
    wire.handle_event({"type": "response.listen", "epoch": 4})
    assert wire._server_epoch_seen == 4
    assert not wire.model_listen_current({
        "type": "response.listen", "epoch": 3,
    })
    assert wire.model_listen_current({
        "type": "response.listen", "epoch": 4,
    })


def test_late_output_clear_cannot_mute_recovered_native_response():
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "old",
        "response": {"id": "old", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    assert wire.handle_event(delta("old", epoch=0)) is not None
    wire.interrupt()
    # STOP and output clear each advance the native server generation.
    wire.append_audio(bytes(32000), speech=False)
    wire.handle_event({
        "type": "response.created", "response_id": "new",
        "response": {"id": "new", "metadata": {"duplex_event": {"epoch": 2}}},
    })
    assert wire.handle_event(delta("new", epoch=2)) is not None
    # Delayed old clear, including the anonymous OpenAI-compatible form,
    # cannot mute a fresh response. Explicit current response clear can.
    wire.handle_event({"type": "output_audio_buffer.cleared",
                       "response_id": "old"})
    assert wire.handle_event(delta("new", epoch=2)) is not None
    wire.handle_event({"type": "output_audio_buffer.cleared"})
    assert wire.handle_event(delta("new", epoch=2)) is not None
    wire.handle_event({"type": "output_audio_buffer.cleared",
                       "response_id": "new"})
    assert wire.handle_event(delta("new", epoch=2)) is None


def test_epochless_native_delta_cannot_restart_audio_after_barge():
    wire = OmniDuplexWire()
    wire.handle_event({
        "type": "response.created", "response_id": "old",
        "response": {"id": "old", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    wire.interrupt()
    wire.append_audio(bytes(32000), speech=False)
    wire.handle_event({
        "type": "response.created", "response_id": "new",
        "response": {"id": "new", "metadata": {"duplex_event": {"epoch": 2}}},
    })
    for missing in (None, {}, {"epoch": None}, {"epoch": "2"}):
        packet = delta("new", epoch=2)
        if missing is None:
            packet.pop("metadata")
        else:
            packet["metadata"] = missing
        assert wire.handle_event(packet) is None
    # A genuine current-epoch delta is still allowed after the interruption.
    assert wire.handle_event(delta("new", epoch=2)) is not None
    assert wire.handle_event(delta("new", epoch=1)) is None


def test_native_handshake_requires_epoch_on_response_and_pcm_delta():
    wire = OmniDuplexWire()
    wire.handle_event({"type": "session.created", "session": {"epoch": 5}})
    wire.handle_event({"type": "response.created", "response_id": "missing"})
    assert wire.response_id is None
    wire.handle_event({
        "type": "response.created", "response_id": "old",
        "response": {"metadata": {"duplex_event": {"epoch": 4}}},
    })
    assert wire.response_id is None
    wire.handle_event({
        "type": "response.created", "response_id": "current",
        "response": {"metadata": {"duplex_event": {"epoch": 5}}},
    })
    assert wire.response_id == "current"
    stale = delta("current", epoch=5)
    stale.pop("metadata")
    assert wire.handle_event(stale) is None
    assert wire.handle_event(delta("current", epoch=4)) is None
    assert wire.handle_event(delta("current", epoch=5)) is not None


def test_playback_ack_rejects_absent_or_interrupted_speaker_authority():
    """A matching None response ID is not evidence of physical playback."""
    wire = OmniDuplexWire()
    for invalid in (None, ""):
        with pytest.raises(ValueError, match="playback evidence"):
            wire.playback_ack(response_id=invalid, actually_played_ms=0)
    wire.handle_event({
        "type": "response.created", "response_id": "live",
        "response": {"id": "live", "metadata": {"duplex_event": {"epoch": 0}}},
    })
    with pytest.raises(ValueError, match="playback evidence"):
        wire.playback_ack(response_id="live", actually_played_ms=0)
    wire.handle_event(delta("live"))
    wire.interrupt()
    with pytest.raises(ValueError, match="playback evidence"):
        wire.playback_ack(response_id="live", actually_played_ms=0)


def test_duplicate_created_never_reopens_or_resets_playback_progress():
    wire = OmniDuplexWire()
    created = {
        "type": "response.created",
        "response_id": "same-response",
        "response": {
            "id": "same-response",
            "metadata": {"duplex_event": {"epoch": 0}},
        },
    }
    wire.handle_event(created)
    assert wire.handle_event(delta("same-response")) is not None
    assert wire.generated_bytes == 4800
    ack = wire.playback_ack(response_id="same-response", actually_played_ms=100)
    assert ack["played_ms"] == 100

    # Duplicate delivery must neither reset PCM counters nor allow the same
    # speaker position to be acknowledged twice.
    assert wire.handle_event(created) is None
    assert wire.generated_bytes == 4800
    assert wire.played_ms == 100
    with pytest.raises(ValueError, match="playback evidence"):
        wire.playback_ack(response_id="same-response", actually_played_ms=100)

    wire.handle_event({"type": "response.done", "response_id": "same-response"})
    assert not wire.accept_output
    assert wire.handle_event(created) is None
    assert not wire.accept_output
    assert wire.generated_bytes == 4800

    # A genuinely new response keeps the ordinary backend scheduling path.
    wire.handle_event({
        "type": "response.created",
        "response_id": "next-response",
        "response": {
            "id": "next-response",
            "metadata": {"duplex_event": {"epoch": 1}},
        },
    })
    assert wire.response_id == "next-response"
    assert wire.generated_bytes == 0
    assert wire.played_ms == 0
    assert wire.accept_output

def test_superseded_response_identity_cannot_reclaim_same_epoch():
    wire = OmniDuplexWire()
    wire.handle_event({"type": "session.created", "session": {"epoch": 5}})

    def created(response_id, epoch=5):
        return {
            "type": "response.created", "response_id": response_id,
            "response": {"id": response_id,
                         "metadata": {"duplex_event": {"epoch": epoch}}},
        }

    wire.handle_event(created("first"))
    assert wire.handle_event(delta("first", epoch=5)) is not None
    wire.handle_event({"type": "response.done", "response_id": "first"})
    wire.handle_event(created("second"))
    assert wire.handle_event(delta("second", epoch=5)) is not None
    wire.playback_ack(response_id="second", actually_played_ms=100)
    wire.handle_event(created("first"))
    assert wire.response_id == "second"
    assert wire.generated_bytes == 4800
    assert wire.played_ms == 100
    assert wire.handle_event(delta("first", epoch=5)) is None
    assert wire.handle_event(delta("second", epoch=5)) is not None
    wire.handle_event(created("third", epoch=6))
    assert wire.response_id == "third"
    wire.handle_event(created("second"))
    assert wire.response_id == "third"


def test_response_replay_tracking_never_evicts_current_epoch_identity(monkeypatch):
    wire = OmniDuplexWire()
    monkeypatch.setattr(wire, "MAX_RESPONSES_PER_EPOCH", 2)

    def created(response_id, epoch=0):
        return {"type": "response.created", "response_id": response_id,
                "epoch": epoch}

    wire.handle_event(created("one"))
    wire.handle_event(created("two"))
    with pytest.raises(RuntimeError, match="replay window exhausted"):
        wire.handle_event(created("three"))
    wire.handle_event(created("one"))
    assert wire.response_id == "two"
    wire.handle_event(created("three", epoch=1))
    assert wire.response_id == "three"

@pytest.mark.parametrize("conflict", ["outer_id", "nested_id", "native_id", "epoch", "bool_epoch"])
def test_response_created_rejects_conflicting_envelope_before_changing_authority(conflict):
    wire = OmniDuplexWire()
    wire.handle_event({"type": "session.created", "session": {"epoch": 1}})
    wire.handle_event({
        "type": "response.created", "response_id": "current",
        "response": {"id": "current", "metadata": {"duplex_event": {"epoch": 1}}},
    })
    assert wire.handle_event(delta("current", epoch=1)) is not None

    event = {
        "type": "response.created", "response_id": "candidate",
        "response": {"id": "candidate", "metadata": {"duplex_event": {
            "response_id": "candidate", "epoch": 1,
        }}},
    }
    if conflict == "outer_id":
        event["response_id"] = None
    elif conflict == "nested_id":
        event["response"]["id"] = "foreign"
    elif conflict == "native_id":
        event["response"]["metadata"]["duplex_event"]["response_id"] = "foreign"
    elif conflict == "epoch":
        event["epoch"] = 2
    else:
        event["epoch"] = True

    with pytest.raises(ValueError, match="identity|epoch"):
        wire.handle_event(event)
    assert wire.response_id == "current"
    assert wire.generated_bytes == 4800
    assert wire.handle_event(delta("candidate", epoch=1)) is None
    assert wire.handle_event(delta("current", epoch=1)) is not None

    wire.handle_event({
        "type": "response.created", "response_id": "candidate", "epoch": 1,
        "response": {"id": "candidate", "metadata": {"duplex_event": {
            "response_id": "candidate", "epoch": 1,
        }}},
    })
    assert wire.response_id == "candidate"
    assert wire.handle_event(delta("candidate", epoch=1)) is not None


def test_i2s_receipt_requires_started_and_transmitted_prefix():
    prefix = I2sTransmissionPrefix()
    assert not prefix.begin_send()
    assert not prefix.accept(60)
    prefix.started = True
    assert not prefix.accept(60)
    assert prefix.begin_send()
    assert not prefix.begin_send()
    prefix.finish_send(True)
    assert prefix.committed_ms == 0
    for invalid in (True, 0, 59, 60.0, 120, None, [], {}):
        assert not prefix.accept(invalid)
    assert prefix.accept(60)
    assert not prefix.accept(60)
    assert not prefix.accept(120)
    assert prefix.begin_send()
    assert prefix.accept(120)
    assert not prefix.accept(120)
    assert prefix.committed_ms == 60
    prefix.finish_send(True)
    assert prefix.committed_ms == 120


@pytest.mark.parametrize("success", [True, False])
def test_i2s_receipt_racing_send_stays_provisional(success):
    prefix = I2sTransmissionPrefix(started=True)
    assert prefix.begin_send()
    assert prefix.accept(60)
    assert not prefix.accept(120)
    assert prefix.committed_ms == 0
    prefix.finish_send(success)
    assert prefix.committed_ms == (60 if success else 0)
    assert prefix.sent_ms == (60 if success else 0)
    assert prefix.begin_send() is success
    if not success:
        assert not prefix.accept(60)


def test_failed_i2s_send_never_accepts_late_receipt_or_retries():
    prefix = I2sTransmissionPrefix(started=True)
    assert prefix.begin_send()
    prefix.finish_send(True)
    assert prefix.accept(60)
    assert prefix.begin_send()
    assert prefix.accept(120)
    prefix.finish_send(False)
    assert prefix.committed_ms == 60
    assert not prefix.accept(120)
    assert not prefix.begin_send()
    assert I2sTransmissionPrefix(started=True).committed_ms == 0
