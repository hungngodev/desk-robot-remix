import importlib
import importlib.util

import pytest


def core(**kwargs):
    assert importlib.util.find_spec("desk_robot.live_turns") is not None, "Missing live-turn core"
    return importlib.import_module("desk_robot.live_turns").LiveTurns(**kwargs)


def connected(**kwargs):
    value = core(**kwargs)
    value.set_connected(True)
    return value


def offer(value, jpeg, *, captured_at, now=None, connection_epoch=None):
    """Synchronous test capture; delayed callback tests supply their saved token."""
    return value.offer_frame(
        jpeg,
        captured_at=captured_at,
        now=captured_at if now is None else now,
        connection_epoch=value.connection_epoch if connection_epoch is None else connection_epoch,
    )


def test_interruption_rejects_late_audio_and_invalidates_already_popped_audio():
    value = connected()
    old_epoch = value.epoch
    assert value.queue_audio(old_epoch, b"\x01\x00" * 4)
    in_flight = value.pop_audio()
    assert value.queue_audio(old_epoch, b"\x02\x00" * 3)

    directive = value.interrupt()

    assert directive.reason == "interrupted"
    assert directive.discarded_bytes == 6
    assert directive.epoch > old_epoch
    assert not value.is_current(in_flight.epoch)
    assert not value.queue_audio(old_epoch, b"\x03\x00")
    assert value.pop_audio() is None
    assert value.queue_audio(directive.epoch, b"\x04\x00")
    assert value.pop_audio().pcm == b"\x04\x00"


def test_overflow_is_explicit_and_keeps_queue_bounded_without_dropping_silently():
    value = connected(max_audio_bytes=8)
    assert value.queue_audio(value.epoch, b"\x01\x00" * 3)
    with pytest.raises(BufferError, match="capacity"):
        value.queue_audio(value.epoch, b"\x02\x00" * 2)
    assert value.queued_audio_bytes == 6
    assert value.pop_audio().pcm == b"\x01\x00" * 3
    assert value.queued_audio_bytes == 0


def test_pcm_queue_copies_mutable_input_and_rejects_incomplete_samples():
    value = connected()
    pcm = bytearray(b"\x01\x00")
    assert value.queue_audio(value.epoch, pcm)
    pcm[:] = b"\xff\xff"
    assert value.pop_audio().pcm == b"\x01\x00"
    with pytest.raises(ValueError, match="16-bit"):
        value.queue_audio(value.epoch, b"x")


def test_disconnect_and_reconnect_cannot_reuse_old_audio_or_enable_proactivity():
    value = connected(heartbeat_interval=2)
    value.enable_proactivity(now=0)
    offer(value, b"old jpeg", captured_at=1)
    old_epoch = value.epoch
    value.queue_audio(old_epoch, b"\x01\x00")

    directive = value.set_connected(False)
    assert directive.reason == "disconnected"
    assert not value.queue_audio(old_epoch, b"\x02\x00")
    assert value.pop_audio() is None
    assert not offer(value, b"late jpeg", captured_at=2)

    value.set_connected(True)
    assert value.epoch > old_epoch
    offer(value, b"fresh jpeg", captured_at=3)
    assert value.poll_observation(now=4) is None
    value.enable_proactivity(now=4)
    offer(value, b"fresh later jpeg", captured_at=6)
    assert value.poll_observation(now=6) is not None


def test_latest_video_frame_replaces_old_frames_and_is_paced():
    value = connected(frame_interval=1, frame_max_age=2)
    assert offer(value, b"frame one", captured_at=0)
    assert offer(value, b"frame two", captured_at=0.1)
    assert value.take_video_frame(now=0.2).jpeg == b"frame two"
    assert offer(value, b"frame three", captured_at=0.3)
    assert value.take_video_frame(now=0.5) is None
    assert value.take_video_frame(now=1.2).jpeg == b"frame three"
    assert value.take_video_frame(now=2.2) is None  # Same frame is not resent.


def test_stale_future_or_out_of_order_frames_do_not_become_current_video():
    value = connected(frame_max_age=1)
    offer(value, b"current", captured_at=5)
    assert not offer(value, b"older callback", captured_at=4)
    assert value.take_video_frame(now=4.9) is None
    assert value.take_video_frame(now=6.1) is None
    offer(value, b"new", captured_at=6.2)
    assert value.take_video_frame(now=6.2).jpeg == b"new"


def test_jpeg_slot_has_a_separate_size_limit():
    value = connected(max_jpeg_bytes=4)
    offer(value, b"jpeg", captured_at=0)
    with pytest.raises(BufferError, match="JPEG"):
        offer(value, b"oversized", captured_at=0)
    assert value.take_video_frame(now=0).jpeg == b"jpeg"


def test_heartbeat_needs_opt_in_due_time_and_fresh_frame():
    value = connected(heartbeat_interval=5, frame_max_age=1)
    offer(value, b"jpeg", captured_at=0)
    assert value.poll_observation(now=0) is None
    value.enable_proactivity(now=0)
    assert value.poll_observation(now=4) is None
    assert value.poll_observation(now=5) is None  # Old image cannot prompt observation.
    offer(value, b"fresh", captured_at=5)
    request = value.poll_observation(now=5)
    assert request.jpeg == b"fresh"
    assert request.captured_at == 5
    assert request.epoch == value.epoch
    assert request.prompt
    assert value.poll_observation(now=6) is None  # Pending request is reserved.


@pytest.mark.parametrize("busy", ["user", "model", "tool"])
def test_heartbeat_does_not_interrupt_any_busy_turn(busy):
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    value.set_busy(value.epoch, **{busy: True})
    assert value.poll_observation(now=1) is None
    value.set_busy(value.epoch, **{busy: False})
    assert value.poll_observation(now=1) is not None


def test_quiet_mode_blocks_proactive_requests_without_using_up_cooldown():
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    value.set_quiet(True)
    assert value.poll_observation(now=1) is None
    value.set_quiet(False)
    assert value.poll_observation(now=1) is not None


def test_finishing_heartbeat_preserves_cooldown_and_old_completion_cannot_clear_new_one():
    value = connected(heartbeat_interval=2)
    value.enable_proactivity(now=0)
    offer(value, b"one", captured_at=2)
    old = value.poll_observation(now=2)
    assert value.finish_observation(old.epoch)
    offer(value, b"two", captured_at=3)
    assert value.poll_observation(now=3) is None
    value.interrupt()
    offer(value, b"three", captured_at=4)
    current = value.poll_observation(now=4)
    assert current is not None
    assert not value.finish_observation(old.epoch)
    assert value.poll_observation(now=5) is None
    assert value.finish_observation(current.epoch)


def test_interrupt_does_not_pretend_running_tools_or_capture_are_idle():
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    value.set_busy(value.epoch, user=True, tool=True)
    value.interrupt()
    offer(value, b"jpeg", captured_at=2)
    assert value.poll_observation(now=2) is None
    value.set_busy(value.epoch, user=False)
    assert value.poll_observation(now=2) is None
    value.set_busy(value.epoch, tool=False)
    assert value.poll_observation(now=2) is not None


def test_quiet_mode_invalidates_an_already_requested_proactive_reply():
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    request = value.poll_observation(now=1)
    directive = value.set_quiet(True)
    assert directive.reason == "quiet"
    assert directive.epoch > request.epoch
    assert not value.queue_audio(request.epoch, b"\x01\x00")
    assert not value.finish_observation(request.epoch)


def test_repeated_observation_epochs_cannot_be_completed_by_an_old_callback():
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    offer(value, b"first", captured_at=1)
    first = value.poll_observation(now=1)
    assert value.finish_observation(first.epoch)
    offer(value, b"second", captured_at=2)
    second = value.poll_observation(now=2)
    assert second.epoch > first.epoch
    assert not value.finish_observation(first.epoch)
    assert value.poll_observation(now=3) is None


def test_connection_transition_clears_old_image_and_requires_fresh_activity_state():
    value = connected(heartbeat_interval=1)
    value.set_busy(value.epoch, model=True)
    offer(value, b"old", captured_at=0)
    value.set_connected(False)
    value.set_connected(True)
    value.enable_proactivity(now=0)
    assert value.take_video_frame(now=1) is None
    offer(value, b"new", captured_at=1)
    assert value.poll_observation(now=1) is None  # Connection does not clear busy flags.
    value.set_busy(value.epoch, model=False)
    assert value.poll_observation(now=1) is not None


def test_disabled_proactivity_cannot_auto_resume_and_disconnected_opt_in_is_rejected():
    value = core(heartbeat_interval=1)
    with pytest.raises(RuntimeError, match="connected"):
        value.enable_proactivity(now=0)
    value.set_connected(True)
    value.enable_proactivity(now=0)
    value.disable_proactivity()
    offer(value, b"jpeg", captured_at=2)
    assert value.poll_observation(now=2) is None


def test_manual_turn_cancels_pending_observation_and_requires_connection():
    value = core(heartbeat_interval=1)
    with pytest.raises(RuntimeError, match="connected"):
        value.begin_turn()
    value.set_connected(True)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    request = value.poll_observation(now=1)
    value.queue_audio(request.epoch, b"\x01\x00")

    directive = value.begin_turn()

    assert directive.reason == "new_turn"
    assert directive.discarded_bytes == 2
    assert not value.finish_observation(request.epoch)
    assert not value.queue_audio(request.epoch, b"\x02\x00")
    assert value.queue_audio(directive.epoch, b"\x03\x00")


def test_disabling_pending_observation_returns_a_flush_and_rejects_late_reply():
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    request = value.poll_observation(now=1)

    directive = value.disable_proactivity()

    assert directive.reason == "proactivity_disabled"
    assert not value.queue_audio(request.epoch, b"\x01\x00")
    assert not value.finish_observation(request.epoch)
    assert value.poll_observation(now=2) is None


def test_buffered_playback_blocks_proactive_observation_even_without_busy_flags():
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    value.queue_audio(value.epoch, b"\x01\x00")
    assert value.poll_observation(now=1) is None
    value.pop_audio()  # The adapter must keep model busy until device playback also drains.
    assert value.poll_observation(now=1) is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_audio_bytes": 0},
        {"frame_interval": 0},
        {"frame_max_age": float("inf")},
        {"heartbeat_interval": -1},
    ],
)
def test_invalid_limits_fail_before_accepting_media(kwargs):
    with pytest.raises(ValueError):
        core(**kwargs)


def test_reconnected_camera_rejects_callback_from_previous_connection():
    value = connected()
    old_connection = value.connection_epoch
    value.set_connected(False)
    value.set_connected(True)
    assert not offer(value, b"old capture", captured_at=1, now=1.1, connection_epoch=old_connection)
    assert value.take_video_frame(now=1.1) is None


def test_slow_or_future_capture_cannot_replace_a_usable_current_frame():
    value = connected(frame_max_age=1)
    token = value.connection_epoch
    assert offer(value, b"current", captured_at=2, now=2, connection_epoch=token)
    assert not offer(value, b"late", captured_at=0, now=2.1, connection_epoch=token)
    assert not offer(value, b"future", captured_at=100, now=2.1, connection_epoch=token)
    assert value.take_video_frame(now=2.1).jpeg == b"current"
    assert offer(value, b"newer", captured_at=2.2, now=2.2, connection_epoch=token)
    assert value.take_video_frame(now=3.1).jpeg == b"newer"


def test_observation_exposes_the_flush_needed_before_sending_its_new_epoch():
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    request = value.poll_observation(now=1)
    assert request.flush.epoch == request.epoch
    assert request.flush.reason == "observation"


@pytest.mark.parametrize("cancel", ["quiet", "disable"])
def test_cancelling_spontaneous_speech_after_generation_stops_queued_and_late_audio(cancel):
    value = connected(heartbeat_interval=1)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    request = value.poll_observation(now=1)
    assert value.finish_observation(request.epoch)
    value.queue_audio(request.epoch, b"\x01\x00")

    directive = value.set_quiet(True) if cancel == "quiet" else value.disable_proactivity()

    assert directive is not None
    assert directive.discarded_bytes == 2
    assert not value.queue_audio(request.epoch, b"\x02\x00")
    assert value.pop_audio() is None


def test_old_completion_cannot_clear_busy_state_of_a_new_turn():
    value = connected(heartbeat_interval=1)
    old_epoch = value.epoch
    value.set_busy(old_epoch, model=True)
    current = value.begin_turn().epoch
    value.set_busy(current, model=True)
    assert not value.set_busy(old_epoch, model=False)
    value.enable_proactivity(now=0)
    offer(value, b"jpeg", captured_at=1)
    assert value.poll_observation(now=1) is None
    assert value.set_busy(current, model=False)
    assert value.poll_observation(now=1) is not None


def test_camera_connection_token_survives_normal_turns_but_not_reconnect():
    value = connected()
    token = value.connection_epoch
    value.begin_turn()
    assert offer(value, b"capture in flight", captured_at=1, now=1.1, connection_epoch=token)
    frame = value.take_video_frame(now=1.1)
    assert value.is_connection_current(frame.connection_epoch)
    value.set_connected(False)
    value.set_connected(True)
    assert not value.is_connection_current(frame.connection_epoch)


def test_reconnection_retains_busy_flags_until_current_owner_reconciles_them():
    value = connected(heartbeat_interval=1)
    old_epoch = value.epoch
    assert value.set_busy(old_epoch, user=True, model=True, tool=True)
    value.set_connected(False)
    assert not value.set_busy(old_epoch, user=False, model=False, tool=False)
    value.set_connected(True)
    assert not value.set_busy(old_epoch, user=False, model=False, tool=False)
    value.enable_proactivity(now=0)
    offer(value, b"fresh", captured_at=1)
    assert value.poll_observation(now=1) is None
    assert value.set_busy(value.epoch, user=False, model=False, tool=False)
    assert value.poll_observation(now=1) is not None


def test_quiet_mode_preserves_an_explicit_user_requested_turn():
    value = connected()
    turn = value.begin_turn().epoch
    assert value.queue_audio(turn, b"\x01\x00")
    assert value.set_quiet(True) is None
    assert value.is_current(turn)
    assert value.pop_audio().pcm == b"\x01\x00"


@pytest.mark.parametrize("invalid", [0, 1, "", "false", [], {}])
def test_busy_and_quiet_flags_reject_nonboolean_values(invalid):
    value = connected(heartbeat_interval=1)
    current = value.epoch
    for field in ("user", "model", "tool"):
        with pytest.raises(ValueError, match="booleans"):
            value.set_busy(current, **{field: invalid})
    with pytest.raises(ValueError, match="boolean"):
        value.set_quiet(invalid)
    # Failed validation cannot accidentally suppress an otherwise permitted
    # spontaneous observation or alter current turn ownership.
    value.enable_proactivity(now=0)
    offer(value, b"fresh", captured_at=1)
    assert value.poll_observation(now=1) is not None


def test_absent_observation_never_reports_successful_completion():
    value = connected(heartbeat_interval=1)
    # No real observation has ever been acquired. A missing identity is not
    # permission to report a successful completed operation.
    assert not value.finish_observation(None)
    assert not value.finish_observation(value.epoch)
    value.enable_proactivity(now=0)
    offer(value, b"fresh", captured_at=1)
    request = value.poll_observation(now=1)
    assert request is not None
    assert not value.finish_observation(None)
    assert value.finish_observation(request.epoch)
    assert not value.finish_observation(request.epoch)
    assert not value.finish_observation(None)


@pytest.mark.parametrize("invalid", [None, 0, 1, "", "false", []])
def test_connection_state_rejects_nonboolean_values(invalid):
    value = connected()
    epoch = value.epoch
    connection_epoch = value.connection_epoch
    with pytest.raises(ValueError, match="boolean"):
        value.set_connected(invalid)
    assert value.is_current(epoch)
    assert value.connection_epoch == connection_epoch


def test_boolean_generation_cannot_impersonate_first_live_turn_or_camera_connection():
    value = connected(heartbeat_interval=1)
    # Python bool is a subclass of int: True == 1 must never confer
    # possession of this first connected audio or camera generation.
    assert value.epoch == value.connection_epoch == 1
    assert not value.is_current(True)
    assert not value.is_connection_current(True)
    assert not value.set_busy(True, model=False)
    assert not value.queue_audio(True, b"\x01\x00")
    assert not offer(value, b"untrusted frame", captured_at=1, now=1,
                     connection_epoch=True)
    assert value.queued_audio_bytes == 0
    assert value.take_video_frame(now=1) is None
    # The legitimate integer tokens still work without granting permission
    # to model speech or moving the robot.
    assert value.is_current(1)
    assert value.is_connection_current(1)
    assert value.set_busy(1, model=True)
    assert value.queue_audio(1, b"\x02\x00")
    assert offer(value, b"real frame", captured_at=1, now=1,
                 connection_epoch=1)
    assert value.take_video_frame(now=1).jpeg == b"real frame"


@pytest.mark.parametrize("bad_clock", [10 ** 400, -(10 ** 400)])
def test_extreme_integer_monotonic_clocks_fail_with_value_error(bad_clock):
    with pytest.raises(ValueError, match="finite monotonic"):
        core(frame_interval=bad_clock)
    value = connected()
    with pytest.raises(ValueError, match="finite monotonic"):
        offer(value, b"untrusted", captured_at=bad_clock, now=0)
    with pytest.raises(ValueError, match="finite monotonic"):
        value.take_video_frame(now=bad_clock)
    assert value.take_video_frame(now=0) is None
