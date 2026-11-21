"""One owned Feather room station, read-only source and five-pet sharing."""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace

import pytest
from desk_robot.brain_context import compose_brain_context
from desk_robot.config import RobotConfig, Settings
from desk_robot.multimodal import CameraFrameHub
from desk_robot.room_station import MAX_FRAME_BYTES, RoomSerialFeed, RoomStationDecoder
from desk_robot.soil_calibration import SoilCalibration


class SynchronizedFakePort:
    """Model the physical Feather causal ACK without accepting old USB JSON."""

    def write(self, request):
        assert request.startswith(b"SYNC ") and request.endswith(b"\n")
        nonce = request[5:-1]
        assert len(nonce) == 16 and all(c in b"0123456789abcdef" for c in nonce)
        self._session_reply = b"SYNC_ACK " + nonce + b"\n"
        return len(request)

    def _read_session_reply(self):
        reply = getattr(self, "_session_reply", None)
        if reply is not None:
            self._session_reply = None
        return reply


def frame(seq=1, clock=1000):
    return {
        "v": 1, "station": "room-pod-01", "seq": seq, "at_ms": clock,
        "readings": {
            "scd40": {
                "valid": True, "sample_ms": clock, "co2_ppm": 630,
                "temp_c": 23.4, "humidity_pct": 46.1,
            },
            "bme688": {
                "valid": True, "sample_ms": clock, "temp_c": 24.0,
                "humidity_pct": 44.5, "pressure_pa": 100830,
                "gas_ohms": 35201,
            },
            "ld2410c": {
                "valid": True, "sample_ms": clock, "presence": True,
                "stationary": True, "moving": False,
                "stationary_cm": 107, "moving_cm": 0,
            },
            "soil": {"valid": False},
            "amg8833": {"valid": True, "sample_ms": clock, "pixels_c": [23.0] * 64},
        },
    }


def accept(payload, *, decoder=None, now=1.0):
    return (decoder or RoomStationDecoder()).accept(
        json.dumps(payload).encode(), now=now,
    )


@pytest.mark.parametrize("raw", [0, 4095, -1, 5000, True, 2250.0, "2250"])
def test_soil_adc_contract_rejects_saturation_and_noninteger_without_calibration(raw):
    payload = frame(seq=4, clock=5000)
    payload["readings"]["soil"] = {
        "valid": True, "sample_ms": 5000, "raw_adc": raw,
    }
    with pytest.raises(ValueError, match="Invalid or saturated raw soil ADC"):
        RoomStationDecoder().accept(json.dumps(payload), now=10.0)


def test_measured_soil_calibration_flows_into_shared_room_observation():
    payload = frame(seq=2, clock=5000)
    payload["readings"]["soil"] = {
        "valid": True, "sample_ms": 5000, "raw_adc": 2250,
    }
    raw = RoomStationDecoder().accept(json.dumps(payload), now=10.0)
    assert "Station soil probe raw ADC 2250" in raw.summary
    assert "relative soil moisture" not in raw.summary

    decoder = RoomStationDecoder(soil_calibration=SoilCalibration(3200, 1300))
    observation = decoder.accept(json.dumps(payload), now=10.0)
    assert "Station soil probe raw ADC 2250" in observation.summary
    assert "relative soil moisture 50% from measured calibration" in observation.summary
    assert not observation.motion_authorized
    assert not observation.charging_authorized
    assert not observation.person_identified

    payload["readings"]["soil"] = {"valid": False}
    payload["seq"], payload["at_ms"] = 3, 6000
    no_soil = decoder.accept(json.dumps(payload), now=11.0)
    assert "relative soil moisture" not in no_soil.summary


def test_room_station_soil_calibration_requires_a_real_pair_and_live_source():
    robots = [RobotConfig(id="robot-01", name="Pip", token_env="A")]
    port = "/dev/cu.usbmodemTEST"
    setting = Settings(robots=robots, room_station_enabled=True,
                       room_station_port=port,
                       room_station_soil_dry_adc=3200,
                       room_station_soil_wet_adc=1300)
    assert (setting.room_station_soil_dry_adc,
            setting.room_station_soil_wet_adc) == (3200, 1300)
    with pytest.raises(ValueError, match="both measured"):
        Settings(robots=robots, room_station_enabled=True,
                 room_station_port=port, room_station_soil_dry_adc=3200)
    with pytest.raises(ValueError, match="requires a real enabled"):
        Settings(robots=robots, room_station_soil_dry_adc=3200,
                 room_station_soil_wet_adc=1300)
    with pytest.raises(ValueError, match="too close"):
        Settings(robots=robots, room_station_enabled=True,
                 room_station_port=port, room_station_soil_dry_adc=2000,
                 room_station_soil_wet_adc=2050)
    with pytest.raises(ValueError):
        Settings(robots=robots, room_station_enabled=True,
                 room_station_port=port, room_station_soil_dry_adc=True,
                 room_station_soil_wet_adc=1300)



@pytest.mark.parametrize("raw", [0, -1, 0.5])
def test_bme688_unstable_zero_gas_is_not_a_valid_room_measurement(raw):
    # Adafruit BME680 2.0.5 endReading() sets gas_resistance=0
    # when the gas heater has not stabilized. Never report a fake 0 ohm.
    payload = frame()
    payload["readings"]["bme688"]["gas_ohms"] = raw
    with pytest.raises(ValueError, match="out of range"):
        accept(payload)
    payload["readings"]["bme688"]["gas_ohms"] = 35201
    evidence = accept(payload)
    assert evidence.readings["bme688"]["gas_ohms"] == 35201


@pytest.mark.parametrize("pixel,valid", [
    (0.0, True), (80.0, True), (-0.25, False), (80.25, False),
    (-40.0, False), (125.0, False),
])
def test_amg8833_high_gain_pixel_range_matches_panasonic(pixel, valid):
    payload = frame()
    payload["readings"]["amg8833"]["pixels_c"][0] = pixel
    if valid:
        assert accept(payload).readings["amg8833"]["pixels_c"][0] == pixel
    else:
        with pytest.raises(ValueError, match="out of range"):
            accept(payload)


def test_shared_room_context_retains_raw_thermal_range_and_radar_distance():
    payload = frame()
    payload["readings"]["amg8833"]["pixels_c"][17] = 37.5
    evidence = accept(payload)
    assert "Station radar detected an echo, stationary 107 cm" in evidence.summary
    assert "Station thermal raw 23.0..37.5 C" in evidence.summary
    assert "unclassified pixels" in evidence.summary
    assert len(evidence.summary) <= 300
    assert evidence.person_identified is False
    assert evidence.motion_authorized is False
    assert evidence.charging_authorized is False

    hub = CameraFrameHub(["robot-01"])
    hub.remember_room(evidence)
    observed = [item for item in hub.interaction_timeline("robot-01", now=1.5)
                if item["channel"] == "room_station"]
    assert len(observed) == 1
    assert "thermal raw 23.0..37.5 C" in observed[0]["content"]
    assert observed[0]["shared_not_robot_eyewitness"] is True

    payload["readings"]["ld2410c"].update(moving=True, stationary=False,
                                           moving_cm=24)
    moving = accept(payload)
    assert "moving 24 cm" in moving.summary
    payload["readings"]["amg8833"] = {"valid": False}
    payload["readings"]["ld2410c"].update(presence=False, moving=False)
    absent = accept(payload)
    assert "thermal raw" not in absent.summary
    assert "stationary 107 cm" not in absent.summary


def test_full_read_only_room_frame_has_provenance_not_actuator_authority():
    evidence = accept(frame())
    assert evidence.seq == 1
    assert evidence.source == "local_usb_shared_station_observation_not_identity"
    assert not evidence.motion_authorized
    assert not evidence.charging_authorized
    assert not evidence.person_identified
    assert "Station CO2 630 ppm" in evidence.summary
    assert "raw gas resistance" in evidence.summary
    assert "radar detected an echo" in evidence.summary
    assert "person" not in evidence.summary.lower()
    assert "VOC ppm" not in evidence.summary
    assert "soil" not in evidence.summary


@pytest.mark.parametrize("change", [
    lambda p: p.update(station="room-pod-02"),
    lambda p: p.update(v=True),
    lambda p: p.update(motor_authorized=True),
    lambda p: p["readings"].update(unknown={"valid": True}),
    lambda p: p["readings"]["scd40"].update(co2_ppm=True),
    lambda p: p["readings"]["scd40"].update(co2_ppm=999999),
    lambda p: p["readings"]["bme688"].update(gas_ohms=float("inf")),
    lambda p: p["readings"]["amg8833"].update(pixels_c=[23.0] * 63),
    lambda p: p["readings"]["ld2410c"].update(
        presence=False, stationary=True
    ),
    lambda p: p["readings"]["soil"].update(raw_adc=777),
    lambda p: p["readings"]["scd40"].update(sample_ms=1000 - 8501),
])
def test_forged_nonfinite_stale_or_unqualified_room_measurements_rejected(change):
    p = frame(clock=10000)
    change(p)
    with pytest.raises(ValueError):
        accept(p)


def test_serial_protocol_rejects_duplicate_fields_and_nonfinite_json():
    decoder = RoomStationDecoder()
    with pytest.raises(ValueError, match="Duplicate"):
        decoder.accept('{"v":1,"v":2}', now=1.0)
    with pytest.raises(ValueError):
        decoder.accept('{"v":NaN}', now=1.0)
    with pytest.raises(ValueError, match="Oversized"):
        decoder.accept(b"x" * 4097, now=1.0)
    with pytest.raises(ValueError):
        decoder.accept(b"\xff\xfe", now=1.0)


def test_earlier_boot_packets_and_duplicate_clock_never_replay_on_same_port():
    decoder = RoomStationDecoder()
    assert accept(frame(41, 5000), decoder=decoder).seq == 41
    with pytest.raises(ValueError, match="Replayed"):
        accept(frame(41, 5000), decoder=decoder)
    with pytest.raises(ValueError, match="Replayed"):
        accept(frame(40, 5100), decoder=decoder)
    with pytest.raises(ValueError, match="Replayed"):
        accept(frame(42, 5000), decoder=decoder)
    assert accept(frame(42, 6000), decoder=decoder).seq == 42
    with pytest.raises(ValueError, match="Replayed"):
        accept(frame(1, 1000), decoder=decoder)
    # Only a real USB close plus reopen creates a new decoder epoch.
    assert accept(frame(1, 1000), decoder=RoomStationDecoder()).seq == 1


def test_uint32_clock_and_sequence_wrap_uses_real_forward_progress():
    decoder = RoomStationDecoder()
    accept(frame(0xffffffff, 0xffffff00), decoder=decoder)
    assert accept(frame(0, 744), decoder=decoder).seq == 0
    with pytest.raises(ValueError, match="Replayed"):
        accept(frame(0xffffffff, 0xffffff00), decoder=decoder)



def test_future_usb_station_clock_does_not_poison_decoder_epoch():
    decoder = RoomStationDecoder()
    assert accept(frame(10, 1000), decoder=decoder, now=10.0).seq == 10
    # Fresh sensor fields matching a forged far-future station millis value
    # are insufficient to change Mac's host reception chronology.
    with pytest.raises(ValueError, match="jumped ahead"):
        accept(frame(11, 800000), decoder=decoder, now=10.1)
    # A rejected packet cannot move seq/time fences; real station recovers.
    assert accept(frame(11, 2000), decoder=decoder, now=11.0).seq == 11
    with pytest.raises(ValueError, match="Backwards Mac"):
        accept(frame(12, 3000), decoder=decoder, now=10.9)
    assert accept(frame(12, 3000), decoder=decoder, now=12.0).seq == 12


def test_cumulative_usb_clock_advance_cannot_launder_future_station_time():
    decoder = RoomStationDecoder()
    accept(frame(1, 1000), decoder=decoder, now=1.0)
    # Individual one-second jumps look plausible against the 3s allowance,
    # but cumulatively a near-instant burst must not claim a future clock.
    for seq in (2, 3, 4):
        assert accept(frame(seq, seq * 1000), decoder=decoder,
                      now=1.0 + seq / 100.0).seq == seq
    with pytest.raises(ValueError, match="jumped ahead"):
        accept(frame(5, 5000), decoder=decoder, now=1.05)
    assert accept(frame(5, 5000), decoder=decoder, now=5.0).seq == 5


def test_shared_room_is_one_short_lived_context_not_robot_memory_or_vision():
    ids = [f"robot-0{i}" for i in range(1, 6)]
    hub = CameraFrameHub(ids)
    evidence = accept(frame(), now=12.0)
    hub.remember_room(evidence)
    for ident in ids:
        timeline = hub.interaction_timeline(ident, now=13.0)
        room = [item for item in timeline if item["channel"] == "room_station"]
        assert len(room) == 1
        assert room[0]["shared_not_robot_eyewitness"] is True
        assert room[0]["identity_verified"] is False
        assert room[0]["physical_action_verified"] is False
        bundle = compose_brain_context([], [], timeline)
        assert "shared room usb station" in bundle.interaction.lower()
        assert "not my own sight" in bundle.interaction.lower()
        assert "630 ppm" in bundle.interaction
    assert all(not hub.tool_history[ident] for ident in ids)
    assert all(not hub.event_history[ident] for ident in ids)
    assert hub.interaction_timeline("robot-01", now=25.0) == []
    # Older completion never overwrites a current room measurement.
    hub.remember_room(replace(evidence, received_at=11.0, summary="stale"))
    assert hub.shared_room == evidence
    hub.close()
    assert hub.shared_room is None


def test_room_configuration_requires_explicit_local_port_and_context_consent():
    robots = [RobotConfig(id="robot-01", name="Pip", token_env="A")]
    with pytest.raises(ValueError, match="real explicit local USB"):
        Settings(robots=robots, room_station_enabled=True)
    with pytest.raises(ValueError, match="real explicit local USB"):
        Settings(robots=robots, room_station_enabled=True,
                 room_station_port="http://camera.invalid")
    with pytest.raises(ValueError, match="needs explicit source"):
        Settings(robots=robots, room_station_context_enabled=True)
    valid = Settings(robots=robots, room_station_enabled=True,
                     room_station_port="/dev/cu.usbmodemTEST",
                     room_station_context_enabled=True)
    assert valid.room_station_enabled


@pytest.mark.parametrize("sensor,field", [
    ("scd40", "co2_ppm"),
    ("scd40", "temp_c"),
    ("bme688", "pressure_pa"),
    ("bme688", "gas_ohms"),
    ("ld2410c", "moving_cm"),
    ("soil", "raw_adc"),
    ("amg8833", "pixels_c"),
])
def test_extreme_room_numeric_values_fail_closed_and_preserve_counter_epoch(
    sensor, field
):
    """A hostile USB JSON integer must not overflow and reconnect the reader."""
    huge = 10 ** 1000
    decoder = RoomStationDecoder()
    assert accept(frame(10, 1000), decoder=decoder).seq == 10
    corrupted = frame(11, 2000)
    if sensor == "soil":
        corrupted["readings"]["soil"] = {
            "valid": True, "sample_ms": 2000, "raw_adc": huge,
        }
    elif sensor == "amg8833":
        corrupted["readings"]["amg8833"]["pixels_c"][0] = huge
    else:
        corrupted["readings"][sensor][field] = huge
    with pytest.raises(ValueError):
        accept(corrupted, decoder=decoder)
    # Invalid frames do not advance sequence/time fences. A subsequent
    # legitimate sample with the same next sequence can recover in place.
    assert accept(frame(11, 2000), decoder=decoder).seq == 11


@pytest.mark.parametrize("clock", [10 ** 1000, -(10 ** 1000)])
def test_unrepresentable_room_receive_clock_is_a_value_error(clock):
    decoder = RoomStationDecoder()
    with pytest.raises(ValueError, match="Finite Mac receive clock"):
        accept(frame(), decoder=decoder, now=clock)
    assert accept(frame(), decoder=decoder, now=1.0).seq == 1


def test_cancelled_room_reader_joins_thread_before_task_exits_even_if_cancelled_twice():
    """A new USB epoch must not overlap the old serial worker after cancellation."""
    async def scenario():
        entered = threading.Event()
        release = threading.Event()
        exited = threading.Event()
        feed = RoomSerialFeed("/dev/cu.test", lambda observation: None)

        def blocked_reader(running):
            entered.set()
            try:
                release.wait(timeout=3)
            finally:
                exited.set()

        feed._read_port = blocked_reader
        task = asyncio.create_task(feed.run(asyncio.Event()))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        task.cancel()  # repeated cancellation must not detach the thread
        await asyncio.sleep(0.02)
        assert not task.done()
        assert not exited.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert exited.is_set()

    asyncio.run(scenario())



def test_room_reader_requests_posix_exclusive_port_ownership(monkeypatch):
    """A cooperating serial monitor cannot silently split the USB byte stream."""
    import sys
    from types import SimpleNamespace

    opens = []

    class FakePort(SynchronizedFakePort):
        def __init__(self, port, *, baudrate, timeout, write_timeout, exclusive):
            opens.append((port, baudrate, timeout, write_timeout, exclusive))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self, size):
            handshake = self._read_session_reply()
            if handshake is not None:
                return handshake
            raise AssertionError("Reader should not run after stop")

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=FakePort))
    feed = RoomSerialFeed("/dev/cu.test", lambda observation: None)
    feed._read_port(lambda: False)
    assert opens == [("/dev/cu.test", 115200, .25, .25, True)]
    assert feed.received == 0
    assert feed.rejected == 0



def test_unterminated_or_oversized_serial_fragments_never_become_room_frames(monkeypatch):
    # pySerial readline() can return partial bytes on timeout or size cap.
    # A syntactically valid JSON suffix is not a new newline-framed packet.
    import sys
    from types import SimpleNamespace

    chunks = [
        json.dumps(frame(1, 1000)).encode(),  # timed out without LF
        json.dumps(frame(2, 2000)).encode() + b"\n",  # prior line suffix
        json.dumps(frame(3, 3000)).encode() + b"\n",  # first real new frame
        b"X" * (MAX_FRAME_BYTES + 1),  # size-limited overlong frame
        json.dumps(frame(4, 4000)).encode() + b"\n",  # overlong line suffix
        json.dumps(frame(5, 5000)).encode() + b"\n",  # recovered frame
        b"",  # one final idle read before ending the worker
    ]
    opened = []
    received = []

    class Port(SynchronizedFakePort):
        def __init__(self, *args, **kwargs):
            self.reads = 0
            opened.append(self)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def readline(self, size):
            assert size == MAX_FRAME_BYTES + 1
            packet = chunks[self.reads]
            self.reads += 1
            return packet

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Port))
    feed = RoomSerialFeed("/dev/cu.test", lambda observation: received.append(observation.seq))
    feed._read_port(lambda: not opened or opened[0].reads < len(chunks))
    assert received == [3, 5]
    assert feed.received == 2
    assert feed.rejected == 2  # one timeout and one overlong frame
    assert feed.callback_failures == 0



def test_recursive_json_parse_error_does_not_restart_usb_replay_epoch(monkeypatch):
    # Pathological USB JSON must not close the port and reset its replay fence.
    import sys
    from types import SimpleNamespace

    import desk_robot.room_station as room_module

    original_loads = room_module.json.loads
    recursive_frames = []

    def loads(value, *args, **kwargs):
        if value.strip() == "[[[":
            recursive_frames.append(value)
            raise RecursionError("Excessively nested USB JSON")
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(room_module.json, "loads", loads)
    chunks = [
        json.dumps(frame(1, 1000)).encode() + b"\n",
        b"[[[\n",
        json.dumps(frame(1, 1000)).encode() + b"\n",
        json.dumps(frame(2, 2000)).encode() + b"\n",
        # Keep the reader active through delivery of the final valid frame.
        # Stopping immediately after readline correctly drops that frame.
        b"",
    ]
    opened = []
    received = []

    class Port:
        def __init__(self, *args, **kwargs):
            self.reads = 0
            opened.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self, size):
            chunk = chunks[self.reads]
            self.reads += 1
            return chunk

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Port))
    feed = RoomSerialFeed("/dev/cu.test", lambda obs: received.append(obs.seq))
    feed._read_port(lambda: not opened or opened[0].reads < len(chunks))
    assert len(opened) == 1
    assert received == [1, 2]
    assert feed.received == 2
    assert feed.rejected == 2
    assert feed.callback_failures == 0
    assert recursive_frames == ["[[[\n"]  # The RecursionError branch ran.


def test_cancel_after_usb_read_discards_retired_station_epoch(monkeypatch):
    # A stop that races the last USB read must not publish its observation.
    import sys
    from types import SimpleNamespace

    alive = {"running": True}
    delivered = []

    class Port:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self, size):
            alive["running"] = False
            return json.dumps(frame(1, 1000)).encode() + b"\n"

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Port))
    feed = RoomSerialFeed("/dev/cu.test", lambda obs: delivered.append(obs.seq))
    feed._read_port(lambda: alive["running"])
    assert delivered == []
    assert feed.received == 0
    assert feed.callback_failures == 0


def test_callback_exception_does_not_reopen_usb_or_reset_replay_fence(monkeypatch):
    """A failed consumer must not turn replayed USB frames into new evidence."""
    import sys
    from types import SimpleNamespace

    opened = []
    packets = [frame(1, 1000), frame(1, 1000), frame(2, 2000)]
    received = []
    feed = RoomSerialFeed("/dev/cu.test", lambda observation: received.append(observation.seq))

    class FakePort:
        def __init__(self, *args, **kwargs):
            opened.append(self)
            self.reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self, size):
            self.reads += 1
            return (json.dumps(packets[self.reads - 1]).encode() + b"\n") if self.reads <= 3 else b""

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=FakePort))
    attempts = []

    def callback(observation):
        attempts.append(observation.seq)
        if len(attempts) == 1:
            raise RuntimeError("application consumer failed")
        received.append(observation.seq)

    feed.on_observation = callback
    # The consumer remains live while the final packet is delivered; a real
    # cancellation between readline and callback must still suppress delivery.
    feed._read_port(lambda: not opened or opened[0].reads < 4)
    assert len(opened) == 1
    assert attempts == [1, 2]
    assert received == [2]
    assert feed.rejected == 1  # replayed frame only
    assert feed.callback_failures == 1  # independent consumer failure
    assert feed.received == 1  # only successfully delivered observations
    assert "callback failed" in feed.last_error


def test_room_callback_failure_is_not_erased_by_clean_reader_shutdown(monkeypatch):
    """A finished worker must not clear a real consumer failure diagnostic."""
    import sys
    from types import SimpleNamespace

    class Port:
        def __init__(self, *args, **kwargs):
            self.reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self, size):
            self.reads += 1
            if self.reads == 1:
                return json.dumps(frame()).encode() + b"\n"
            threading.Event().wait(0.001)
            return b""

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Port))

    async def scenario():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def broken_consumer(observation):
            loop.call_soon_threadsafe(stop.set)
            raise RuntimeError("consumer rejected evidence")

        feed = RoomSerialFeed("/dev/cu.test", broken_consumer)
        await asyncio.wait_for(feed.run(stop), timeout=2)
        assert feed.rejected == 0
        assert feed.callback_failures == 1
        assert feed.received == 0
        assert "Room observation callback failed: RuntimeError" in feed.last_error

        # Only a genuinely reopened port may reset the previous error.
        feed._read_port(lambda: False)
        assert feed.last_error is None

    asyncio.run(scenario())


def test_room_station_summary_preserves_both_moving_and_stationary_radar_targets():
    """LD2410C dual target detection preserves both distance gates."""
    f = frame()
    f["readings"]["ld2410c"]["moving"] = True
    f["readings"]["ld2410c"]["stationary"] = True
    f["readings"]["ld2410c"]["moving_cm"] = 185
    f["readings"]["ld2410c"]["stationary_cm"] = 92
    decoder = RoomStationDecoder()
    obs = decoder.accept(json.dumps(f), now=1.0)
    assert "moving 185 cm, stationary 92 cm" in obs.summary


def test_room_station_summary_preserves_thermal_with_all_sensors_valid():
    """All 5 sensors reporting valid measurements avoids mid-word truncation."""
    calib = SoilCalibration(dry_adc=3200, wet_adc=1300)
    decoder = RoomStationDecoder(soil_calibration=calib)
    f = frame()
    f["readings"]["scd40"]["co2_ppm"] = 1250
    f["readings"]["scd40"]["temp_c"] = 24.8
    f["readings"]["scd40"]["humidity_pct"] = 52.3
    f["readings"]["bme688"]["temp_c"] = 25.1
    f["readings"]["bme688"]["humidity_pct"] = 51.0
    f["readings"]["bme688"]["gas_ohms"] = 120500
    f["readings"]["ld2410c"]["moving"] = True
    f["readings"]["ld2410c"]["stationary"] = True
    f["readings"]["ld2410c"]["moving_cm"] = 210
    f["readings"]["ld2410c"]["stationary_cm"] = 105
    f["readings"]["soil"] = {"valid": True, "sample_ms": 1000, "raw_adc": 2250}
    f["readings"]["amg8833"]["pixels_c"] = [23.2] * 63 + [36.8]
    obs = decoder.accept(json.dumps(f), now=1.0)
    assert "(64 unclassified pixels)" in obs.summary
    assert "Station thermal raw 23.2..36.8 C (64 unclassified pixels)" in obs.summary
    assert obs.summary.endswith("(64 unclassified pixels)")


@pytest.mark.parametrize(("field", "value"), [
    ("pressure_pa", 29999), ("pressure_pa", 125001),
    ("gas_ohms", 0), ("gas_ohms", 1000000001),
])
def test_bme688_out_of_range_values_reject_frame(field, value):
    # Consumer refuses outliers; producer separately marks BME invalid so
    # a single sensor fault cannot suppress otherwise valid station fields.
    payload = frame()
    payload["readings"]["bme688"][field] = value
    with pytest.raises(ValueError, match="Room sensor reading out of range"):
        accept(payload)



def test_usb_reconnect_sync_discards_complete_buffered_old_sensor_frame(monkeypatch):
    """An old valid station JSON must never acquire a new Mac live timestamp."""
    import sys
    from types import SimpleNamespace

    old = json.dumps(frame(100, 5000)).encode() + b"\n"
    new = json.dumps(frame(101, 6000)).encode() + b"\n"
    observed, opened = [], []

    class ReplayPort(SynchronizedFakePort):
        def __init__(self, *args, **kwargs):
            self.reads = 0
            opened.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self, size):
            self.reads += 1
            if self.reads == 1:
                return old  # Valid complete frame buffered before SYNC
            if self.reads == 2:
                return self._read_session_reply()
            if self.reads == 3:
                return new   # Emitted only after current-session ACK
            return b""

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=ReplayPort))
    reader = RoomSerialFeed("/dev/cu.test", lambda obs: observed.append(obs.seq))
    reader._read_port(lambda: not opened or opened[0].reads < 4)
    assert observed == [101]
    assert reader.received == 1
    assert reader.callback_failures == 0


def test_room_station_missing_current_epoch_ack_never_delivers_old_json(monkeypatch):
    """An old or incompatible Feather firmware must not fabricate fresh data."""
    import sys
    from types import SimpleNamespace

    import desk_robot.room_station as room_module

    monkeypatch.setattr(room_module, "USB_SYNC_TIMEOUT_S", 0.01)
    observed = []

    class NoAckPort(SynchronizedFakePort):
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self, size):
            return json.dumps(frame()).encode() + b"\n"

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=NoAckPort))
    reader = RoomSerialFeed("/dev/cu.test", observed.append)
    with pytest.raises(RuntimeError, match="post-connect SYNC unacknowledged"):
        reader._read_port(lambda: True)
    assert not observed
    assert reader.received == 0
