"""One owned Feather room station, read-only source and five-pet sharing."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from desk_robot.brain_context import compose_brain_context
from desk_robot.config import RobotConfig, Settings
from desk_robot.multimodal import CameraFrameHub
from desk_robot.room_station import RoomStationDecoder


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
        assert "shared room USB station" in bundle.interaction.lower()
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
