"""Read-only room station bench report never claims physical qualification."""
import json
import runpy
import stat
from pathlib import Path

import pytest
from desk_robot.room_station import SENSORS, RoomStationDecoder

BENCH = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/bench_room_station.py")
)
capture = BENCH["capture"]


def test_room_bench_report_is_private_and_cannot_replace_existing_receipt(tmp_path):
    save = BENCH["save_private_bench_report"]
    report = tmp_path / "private" / "station.json"
    save(report, {"charging_verified": False})
    assert stat.S_IMODE(report.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    assert json.loads(report.read_text()) == {"charging_verified": False}
    with pytest.raises(FileExistsError):
        save(report, {"charging_verified": True})
    assert json.loads(report.read_text())["charging_verified"] is False

    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(ValueError, match="private mode"):
        save(public / "station.json", {})
    assert not (public / "station.json").exists()

    target = tmp_path / "private" / "existing.json"
    target.write_text("original")
    alias = tmp_path / "private" / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(FileExistsError):
        save(alias, {"overwritten": True})
    assert target.read_text() == "original"


def test_room_bench_report_rejects_untrusted_symlink_ancestor(tmp_path):
    save = BENCH["save_private_bench_report"]
    target = tmp_path / "private"
    target.mkdir(mode=0o700)
    (target / "nested").mkdir(mode=0o700)
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    (shared / "alias").symlink_to(target, target_is_directory=True)
    redirected = shared / "alias" / "nested" / "station.json"
    with pytest.raises(ValueError, match="ancestor symlink"):
        save(redirected, {"read_only_usb_sample_captured": True})
    assert not (target / "nested" / "station.json").exists()


def test_room_bench_symlink_rejection_has_no_directory_creation_side_effect(tmp_path):
    save = BENCH["save_private_bench_report"]
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    (shared / "alias").symlink_to(private, target_is_directory=True)
    target = private / "not_yet_created"
    with pytest.raises(ValueError, match="ancestor symlink"):
        save(shared / "alias" / target.name / "station.json", {"valid": True})
    assert not target.exists()


def test_room_bench_rejects_parent_traversal_before_directory_creation(tmp_path):
    save = BENCH["save_private_bench_report"]
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    # The operating system resolves the alias before '..', while abspath
    # would silently erase both segments prior to alias inspection.
    destination = parent / "alias" / ".." / "created" / "station.json"
    with pytest.raises(ValueError, match="parent traversal"):
        save(destination, {"valid": True})
    assert not (parent / "created").exists()


def test_room_bench_cli_uses_exclusive_private_receipt_writer():
    source = (Path(__file__).resolve().parents[1]
              / "scripts/bench_room_station.py").read_text()
    assert "save_private_bench_report(args.report, result)" in source
    assert "args.report.write_text(" not in source


def _packet(seq: int, station_ms: int) -> bytes:
    readings = {name: {"valid": False} for name in SENSORS}
    readings["scd40"] = {
        "valid": True, "sample_ms": station_ms,
        "co2_ppm": 630, "temp_c": 23.5, "humidity_pct": 48.0,
    }
    return json.dumps({
        "v": 1, "station": "room-pod-01",
        "seq": seq, "at_ms": station_ms, "readings": readings,
    }).encode()


def test_room_bench_counts_real_decoder_receipts_without_sensor_person_claim():
    decoder = RoomStationDecoder()
    first = decoder.accept(_packet(7, 1000), now=1.0)
    second = decoder.accept(_packet(9, 2000), now=1.5)

    class Feed:
        def __init__(self, port, on_observation):
            assert port == "/dev/cu.room"
            self.on_observation = on_observation
            self.rejected = 1
            self.callback_failures = 0

        def _read_port(self, running):
            self.on_observation(first)
            self.on_observation(second)

    result = capture("/dev/cu.room", seconds=1, feed_factory=Feed, clock=lambda: 0.0)
    assert result["accepted_frames"] == 2
    assert result["rejected_frames"] == 1
    assert result["missing_station_sequences"] == 1
    assert result["first_station_sequence"] == 7
    assert result["last_station_sequence"] == 9
    assert result["largest_mac_receive_gap_ms"] == 500.0
    assert result["valid_sensor_frames"]["scd40"] == 2
    assert all(result["valid_sensor_frames"][name] == 0
               for name in SENSORS if name != "scd40")
    assert result["read_only_usb_sample_captured"] is True
    for key in ("device_identity_authenticated", "sensor_accuracy_physically_qualified",
                "station_power_physically_qualified", "charging_verified",
                "motion_authorized"):
        assert result[key] is False
    assert "rail voltage" in result["notes"]


def test_room_bench_callback_failure_cannot_count_partial_usb_receipt():
    from dataclasses import replace

    decoder = RoomStationDecoder()
    genuine = decoder.accept(_packet(7, 1000), now=1.0)
    incomplete = replace(genuine, readings={
        key: value for key, value in genuine.readings.items()
        if key != "amg8833"
    })

    class FailedCallback:
        rejected = 0
        callback_failures = 0

        def __init__(self, port, on_observation):
            self.on_observation = on_observation

        def _read_port(self, running):
            try:
                self.on_observation(incomplete)
            except ValueError:
                self.callback_failures += 1

    report = capture("/dev/cu.test", seconds=1,
                     feed_factory=FailedCallback, clock=lambda: 0)
    assert report["callback_failures"] == 1
    assert report["accepted_frames"] == 0
    assert report["valid_sensor_frames"]["scd40"] == 0
    assert report["first_station_sequence"] is None
    assert report["read_only_usb_sample_captured"] is False


def test_room_bench_records_terminal_blackout_without_another_frame():
    decoder = RoomStationDecoder()
    first = decoder.accept(_packet(5, 1000), now=10.2)

    class OneFrame:
        rejected = 0
        callback_failures = 0

        def __init__(self, port, on_observation):
            self.on_observation = on_observation

        def _read_port(self, running):
            self.on_observation(first)

    ticks = iter((10.0, 15.0))
    report = capture("/dev/cu.test", seconds=5, feed_factory=OneFrame,
                     clock=lambda: next(ticks))
    assert report["accepted_frames"] == 1
    assert report["largest_mac_receive_gap_ms"] is None
    assert report["initial_receive_silence_ms"] == 200.0
    assert report["trailing_receive_silence_ms"] == 4800.0
    assert report["largest_mac_receive_silence_ms"] == 4800.0
    assert report["station_power_physically_qualified"] is False

    class NoFrames(OneFrame):
        def _read_port(self, running):
            pass

    ticks = iter((10.0, 15.0))
    absent = capture("/dev/cu.test", seconds=5, feed_factory=NoFrames,
                     clock=lambda: next(ticks))
    assert absent["accepted_frames"] == 0
    assert absent["largest_mac_receive_silence_ms"] == 5000.0
    assert absent["read_only_usb_sample_captured"] is False


def test_room_bench_transport_failure_does_not_promote_any_physical_gate():
    class Broken:
        rejected = 0
        callback_failures = 0

        def __init__(self, port, on_observation):
            pass

        def _read_port(self, running):
            raise OSError("USB serial unplugged")

    result = capture("/dev/cu.absent", seconds=1, feed_factory=Broken, clock=lambda: 0)
    assert result["serial_error_type"] == "OSError"
    assert result["accepted_frames"] == 0
    assert result["read_only_usb_sample_captured"] is False
    assert result["station_power_physically_qualified"] is False
    assert result["charging_verified"] is False


@pytest.mark.parametrize("port,seconds", [
    ("ttyUSB0", 60), ("/dev/cu.test", 0), ("/dev/cu.test", True),
    ("/dev/cu.test", float("nan")), ("/dev/cu.test", float("inf")),
    ("/dev/cu.test", 3601), ("/dev/cu.test", 10 ** 500),
])
def test_room_bench_requires_explicit_local_port_and_bounded_capture(port, seconds):
    with pytest.raises(ValueError):
        capture(port, seconds=seconds)
