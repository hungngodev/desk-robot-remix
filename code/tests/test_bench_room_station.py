"""Read-only room station bench report never claims physical qualification."""
import json
import runpy
import stat
import sys
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


def test_room_cli_preflights_private_destination_before_usb(monkeypatch, tmp_path):
    main = BENCH["main"]

    def forbidden_capture(*args, **kwargs):
        raise AssertionError("Room USB capture must not start on invalid report path")

    monkeypatch.setitem(main.__globals__, "capture", forbidden_capture)
    argv = ["bench_room_station.py", "--port", "/dev/cu.test",
            "--seconds", "1", "--report"]
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    destination = public / "report.json"
    monkeypatch.setattr(sys, "argv", argv + [str(destination)])
    with pytest.raises(ValueError, match="private mode"):
        main()
    assert not destination.exists()

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    occupied = private / "old.json"
    occupied.write_text("original")
    monkeypatch.setattr(sys, "argv", argv + [str(occupied)])
    with pytest.raises(FileExistsError, match="already exists"):
        main()
    assert occupied.read_text() == "original"

    def read_only_capture(port, *, seconds):
        assert port == "/dev/cu.test"
        assert seconds == 1
        return {"station": "room-pod-01", "charging_verified": False}

    monkeypatch.setitem(main.__globals__, "capture", read_only_capture)
    ready = private / "new.json"
    monkeypatch.setattr(sys, "argv", argv + [str(ready)])
    main()
    assert json.loads(ready.read_text()) == {
        "station": "room-pod-01", "charging_verified": False,
    }
    assert stat.S_IMODE(ready.stat().st_mode) == 0o600


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

    ticks = iter((0.0, 2.0))
    result = capture("/dev/cu.room", seconds=1, feed_factory=Feed,
                     clock=lambda: next(ticks))
    assert result["accepted_frames"] == 2
    assert result["rejected_frames"] == 1
    assert result["missing_station_sequences"] == 1
    assert result["first_station_sequence"] == 7
    assert result["last_station_sequence"] == 9
    assert result["largest_mac_receive_gap_ms"] == 500.0
    assert result["valid_sensor_frames"]["scd40"] == 2
    assert result["new_sensor_acquisitions"]["scd40"] == 2
    assert result["reused_sensor_samples"]["scd40"] == 0
    assert all(result["valid_sensor_frames"][name] == 0
               for name in SENSORS if name != "scd40")
    assert result["read_only_usb_sample_captured"] is True
    for key in ("device_identity_authenticated", "sensor_accuracy_physically_qualified",
                "station_power_physically_qualified", "charging_verified",
                "motion_authorized"):
        assert result[key] is False
    assert "rail voltage" in result["notes"]



@pytest.mark.parametrize(
    ("first_ms", "second_station_ms", "second_sample_ms", "expected_new"),
    [(1000, 2000, 1000, 1), (0xfffffffe, 1, 1, 2)],
)
def test_room_bench_counts_distinct_sensor_acquisitions_not_cached_validity(
    first_ms, second_station_ms, second_sample_ms, expected_new,
):
    """Repeated cached values are not fresh acquisitions; uint32 wrap is valid."""
    decoder = RoomStationDecoder()
    first = decoder.accept(_packet(7, first_ms), now=1.0)
    raw = json.loads(_packet(8, second_station_ms))
    raw["readings"]["scd40"]["sample_ms"] = second_sample_ms
    second = decoder.accept(json.dumps(raw).encode(), now=2.0)

    class Feed:
        rejected = 0
        callback_failures = 0

        def __init__(self, port, on_observation):
            self.on_observation = on_observation

        def _read_port(self, running):
            self.on_observation(first)
            self.on_observation(second)

    ticks = iter((0.0, 3.0))
    report = capture("/dev/cu.test", seconds=3,
                     feed_factory=Feed, clock=lambda: next(ticks))
    assert report["valid_sensor_frames"]["scd40"] == 2
    assert report["new_sensor_acquisitions"]["scd40"] == expected_new
    assert report["reused_sensor_samples"]["scd40"] == 2 - expected_new
    assert report["one_hour_usb_continuity_screen_pass"] is False
    assert report["sensor_accuracy_physically_qualified"] is False


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("seq", True), ("seq", -1), ("seq", 0x100000000),
        ("at_ms", "1000"), ("at_ms", -1), ("at_ms", True),
        ("received_at", float("nan")), ("received_at", float("inf")),
        ("received_at", 10 ** 1000), ("received_at", "1.0"),
    ],
)
def test_room_bench_invalid_callback_metadata_cannot_become_usb_receipt(
    field, bad_value,
):
    from dataclasses import replace

    decoder = RoomStationDecoder()
    legitimate = decoder.accept(_packet(7, 1000), now=1.0)
    invalid = replace(legitimate, **{field: bad_value})

    class MalformedFeed:
        rejected = 0

        def __init__(self, port, on_observation):
            self.on_observation = on_observation
            self.callback_failures = 0

        def _read_port(self, running):
            try:
                self.on_observation(invalid)
            except ValueError:
                self.callback_failures += 1

    report = capture("/dev/cu.synthetic", seconds=1, feed_factory=MalformedFeed,
                     clock=lambda: 0.0)
    assert report["accepted_frames"] == 0
    assert report["callback_failures"] == 1
    assert report["read_only_usb_sample_captured"] is False
    assert report["one_hour_usb_continuity_screen_pass"] is False
    assert report["valid_sensor_frames"]["scd40"] == 0


@pytest.mark.parametrize(
    ("received", "bounds", "expected"),
    [
        ((0.4, 0.8), (0.0, 1.0), True),
        ((-0.1, 0.8), (0.0, 1.0), False),
        ((0.4, 1.1), (0.0, 1.0), False),
        ((0.8, 0.4), (0.0, 1.0), False),
        ((0.4, 0.8), (1.0, 0.0), False),
    ],
)
def test_room_bench_short_usb_receipts_require_real_capture_clock_order(
    received, bounds, expected,
):
    from dataclasses import replace

    decoder = RoomStationDecoder()
    first = decoder.accept(_packet(7, 1000), now=0.4)
    second = decoder.accept(_packet(8, 2000), now=0.8)
    observations = (
        replace(first, received_at=received[0]),
        replace(second, received_at=received[1]),
    )

    class Feed:
        rejected = 0
        callback_failures = 0

        def __init__(self, port, on_observation):
            self.on_observation = on_observation

        def _read_port(self, running):
            for item in observations:
                self.on_observation(item)

    ticks = iter(bounds)
    report = capture("/dev/cu.synthetic", seconds=1, feed_factory=Feed,
                     clock=lambda: next(ticks))
    assert report["accepted_frames"] == 2
    assert report["receive_clock_consistent"] is expected
    assert report["read_only_usb_sample_captured"] is expected
    assert report["one_hour_usb_continuity_screen_pass"] is False
    assert report["device_identity_authenticated"] is False
    assert report["station_power_physically_qualified"] is False


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



def test_room_bench_callback_error_after_valid_frame_blocks_success_receipt():
    """A partial callback failure cannot be hidden by an earlier good USB frame."""
    from dataclasses import replace

    decoder = RoomStationDecoder()
    genuine = decoder.accept(_packet(11, 1000), now=1.0)
    incomplete = replace(genuine, readings={
        key: value for key, value in genuine.readings.items()
        if key != "amg8833"
    })

    class MixedFeed:
        rejected = 0
        callback_failures = 0

        def __init__(self, port, on_observation):
            self.on_observation = on_observation

        def _read_port(self, running):
            self.on_observation(genuine)
            try:
                self.on_observation(incomplete)
            except ValueError:
                self.callback_failures += 1

    report = capture("/dev/cu.test", seconds=1,
                     feed_factory=MixedFeed, clock=lambda: 0.0)
    assert report["accepted_frames"] == 1
    assert report["callback_failures"] == 1
    assert report["first_station_sequence"] == 11
    assert report["valid_sensor_frames"]["scd40"] == 1
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


@pytest.mark.parametrize("fault", [
    "none", "short_request", "short_run", "missing_frame", "sequence_gap",
    "duplicate_sequence", "extra_duplicate", "slow_receipt", "terminal_silence",
    "rejected_frame", "callback_failure", "serial_failure",
])
def test_one_hour_usb_continuity_screen_requires_complete_read_only_receipts(fault):
    """Only an uninterrupted 3,600-report USB run earns a diagnostic pass.

    A fake reader checks the accounting, not a real Feather, power rail,
    sensor calibration, or the station's physical acceptance.
    """
    from desk_robot.room_station import RoomObservation

    class Feed:
        def __init__(self, port, on_observation):
            self.on_observation = on_observation
            self.rejected = int(fault == "rejected_frame")
            self.callback_failures = int(fault == "callback_failure")

        def _read_port(self, running):
            count = (3599 if fault == "missing_frame" else
                     3601 if fault == "extra_duplicate" else 3600)
            for index in range(count):
                seq = index
                if fault == "sequence_gap" and index >= 100:
                    seq += 1
                if fault == "duplicate_sequence" and index == 100:
                    seq -= 1
                if fault == "extra_duplicate" and index == 3600:
                    seq = 3599
                received_at = index + 0.5
                if fault == "slow_receipt" and index == 500:
                    received_at += 0.6
                if fault == "extra_duplicate" and index == 3600:
                    received_at = 3599.75
                self.on_observation(RoomObservation(
                    seq=seq, at_ms=index, received_at=received_at,
                    readings={name: {"valid": False} for name in SENSORS},
                    summary="Simulated USB frame; not physical evidence",
                ))
            if fault == "serial_failure":
                raise OSError("USB disconnected")

    duration = 60 if fault == "short_request" else 3600
    finished = 3599 if fault == "short_run" else (
        3602 if fault == "terminal_silence" else 3600
    )
    ticks = iter((0.0, float(finished)))
    result = capture("/dev/cu.synthetic", seconds=duration,
                     feed_factory=Feed, clock=lambda: next(ticks))
    assert result["one_hour_usb_continuity_screen_pass"] is (fault == "none")
    assert result["device_identity_authenticated"] is False
    assert result["sensor_accuracy_physically_qualified"] is False
    assert result["station_power_physically_qualified"] is False
    assert result["charging_verified"] is False
    assert result["motion_authorized"] is False
    if fault == "sequence_gap":
        assert result["missing_station_sequences"] == 1
    if fault == "extra_duplicate":
        assert result["accepted_frames"] == 3601
        assert result["missing_station_sequences"] == 0
    if fault == "terminal_silence":
        assert result["trailing_receive_silence_ms"] == 2500.0


@pytest.mark.parametrize(
    ("status_output", "status_returncode", "expected"),
    [
        ("", 0, "a" * 40),
        (" M code/scripts/bench_room_station.py\n", 0, None),
        ("?? code/firmware/room_station/src/untracked.cpp\n", 0, None),
        ("", 128, None),
    ],
)
def test_room_bench_exact_source_stamp_requires_clean_checkout(
    monkeypatch, status_output, status_returncode, expected
):
    """A trial from modified, untracked or unverifiable source has no exact SHA."""
    from types import SimpleNamespace

    commands = []

    def fake_git(argv, **kwargs):
        commands.append(argv)
        if argv == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n")
        assert argv == ["git", "status", "--porcelain=v1", "--untracked-files=all"]
        return SimpleNamespace(returncode=status_returncode, stdout=status_output)

    source_sha = BENCH["_git_sha"]
    monkeypatch.setattr(source_sha.__globals__["subprocess"], "run", fake_git)
    assert source_sha() == expected
    assert commands == [
        ["git", "rev-parse", "HEAD"],
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    ]


def test_room_bench_exact_source_stamp_fails_closed_on_git_error(monkeypatch):
    """Git I/O failure cannot attribute a hardware report to a reviewed commit."""
    def failed_git(*args, **kwargs):
        raise OSError("source tree unavailable")

    source_sha = BENCH["_git_sha"]
    monkeypatch.setattr(source_sha.__globals__["subprocess"], "run", failed_git)
    assert source_sha() is None
