import json
from pathlib import Path
from runpy import run_path

import httpx
import pytest
from desk_robot.calibration import Calibration
from desk_robot.transport import HeadError, HttpHead, expected_ack, validate_command

# The USB bench tool is intentionally a standalone script, not a second
# installable robot controller or a package in the firmware/runtime hierarchy.
inspect_status = run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/serial_bench.py")
)["inspect_status"]


@pytest.mark.parametrize(
    "command",
    [
        "drive 41 0 100",
        "drive 0 0 251",
        "drive 0 0 nan",
        "drive 0 0 100\narm",
        "grip 121",
        "lift 59",
        "stop extra",
        "arm ",
        "rearm",  # local body USB recovery is never a network movement command
        "drive 0  0 100",
    ],
)
def test_invalid_commands_rejected(command):
    with pytest.raises(ValueError):
        validate_command(command)


def test_default_drive_duration_matches_body_and_head_ack():
    assert validate_command("drive 20 -20") == "drive"
    assert expected_ack("drive 20 -20") == (
        "OK drive left=20 right=-20 ms=250"
    )
    assert expected_ack("drive 20 -20 50") == (
        "OK drive left=20 right=-20 ms=50"
    )
    for invalid in ("drive 40 40 251", "drive 41 0", "drive 0 0 0"):
        with pytest.raises(ValueError):
            validate_command(invalid)


@pytest.mark.parametrize(
    "reply,identity",
    [
        ("OK drive", "robot-01"),
        ("OK drive left=21 right=20 ms=100", "robot-01"),
        ("OK drive left=20 right=20 ms=100", "robot-02"),
    ],
)
async def test_ack_must_match_command_and_robot(settings, tokens, reply, identity):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "reply": reply, "robot_id": identity})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError):
            await head.command("drive 20 20 100")
        assert len(calls) == 1


async def test_camera_completion_sequence_and_boot_id_protect_five_pet_capture(settings, tokens):
    calls = 0
    frames = [
        ("12", "1", "10000"),
        ("12", "2", "20000"),
        ("12", "2", "20000"),  # replay, must not be a new observation
        ("13", "1", "5000"),   # reset after real Sense reboot
    ]
    async def handler(request):
        nonlocal calls
        assert request.url.path == "/api/camera.jpg"
        index = min(calls, len(frames) - 1)
        calls += 1
        return httpx.Response(200, headers=dict(zip(
            ("X-Desk-Camera-Boot", "X-Desk-Camera-Sequence",
             "X-Desk-Camera-Complete-Us"), frames[index], strict=True,
        )), content=b"\xff\xd8frame")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        assert await head.snapshot() == b"\xff\xd8frame"
        assert await head.snapshot() == b"\xff\xd8frame"
        with pytest.raises(HeadError, match="stale or replayed"):
            await head.snapshot()
        assert await head.snapshot() == b"\xff\xd8frame"
        assert calls == 4


async def test_hardware_camera_requires_true_capture_metadata(settings, tokens):
    async def handler(request):
        return httpx.Response(200, content=b"\xff\xd8unmarked")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client, strict_capture=True)
        with pytest.raises(HeadError, match="metadata"):
            await head.snapshot()


def test_calibration_rejects_examples_and_degenerate_geometry(settings):
    path = settings.robots[0].calibration
    c = Calibration.load(path)
    assert c.ground((100, 100)) == pytest.approx((100, 100))
    data = json.loads(path.read_text())
    data["measured"] = False
    with pytest.raises(ValueError, match="unmeasured"):
        Calibration.model_validate(data).verify_ready()
    data["pixel_points"] = [[0, 0], [10, 0], [20, 0], [30, 0]]
    with pytest.raises(ValueError, match="collinear"):
        Calibration.model_validate(data)


def test_nonfinite_calibration_rejected(settings):
    data = json.loads(settings.robots[0].calibration.read_text())
    data["grip_ground_mm"] = [float("nan"), 100]
    with pytest.raises(ValueError):
        Calibration.model_validate(data)


def test_usb_bench_reads_five_real_range_slots_without_arming():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "imu": {"family": 1, "gyro_id": 212, "aux_id": 73},
        "touch": {"active": False, "count": 2},
        "safety": {"required": True, "ready": False, "fault": "missing_sample", "sensor": 0},
        "ranges": {
            "mm": [50, 51, 49, 52, 200],
            "age_ms": [9, 10, 11, 12, 14],
            "present_mask": 31, "valid_mask": 31,
        },
    }
    result = inspect_status(status)
    assert [s["position"] for s in result["ranges"]] == [
        "front_left", "front_right", "rear_left", "rear_right", "forward",
    ]
    assert [s["distance_mm"] for s in result["ranges"]] == [50, 51, 49, 52, 200]
    assert result["eligible_for_manual_local_rearm"]
    assert result["imu"]["family"] == "berryimu_v1"
    assert result["imu"]["gyro_who_am_i"] == 212
    assert result["imu"]["raw_six_axis_available"] is False
    assert result["imu"]["attitude_interlock_active"] is False
    assert result["local_guard_fault"] == "missing_sample"
    assert not result["physical_qualification_pass"]
    status["ranges"]["present_mask"] = 23
    status["ranges"]["valid_mask"] = 15
    result = inspect_status(status)
    assert not result["ranges"][3]["present"]
    assert not result["ranges"][4]["valid"]
    assert not result["eligible_for_manual_local_rearm"]


def test_usb_bench_reports_raw_six_axis_without_claiming_tilt_safety():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "imu": {"family": 1, "gyro_id": 212, "aux_id": 73,
                "valid": True, "acc": [-32768, 0, 16384],
                "gyro": [-25, 33, 125], "age_ms": 20},
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [50, 50, 50, 50, 200],
                   "age_ms": [5, 6, 7, 8, 9],
                   "present_mask": 31, "valid_mask": 31},
    }
    result = inspect_status(status)
    assert result["imu"]["raw_six_axis_available"] is True
    assert result["imu"]["attitude_interlock_active"] is False
    assert result["imu"]["accelerometer_raw"] == [-32768, 0, 16384]
    assert result["imu"]["gyroscope_raw"] == [-25, 33, 125]
    assert result["imu"]["sample_age_ms"] == 20
    assert result["physical_qualification_pass"] is False
    assert result["imu"]["physical_qualification_pass"] is False

    for bad in (
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": 201},
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": -1},
        {"valid": True, "acc": [1, 2, 32768], "gyro": [4, 5, 6], "age_ms": 1},
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5], "age_ms": 1},
        {"valid": 1, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": 1},
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": "1"},
        {"valid": True, "acc": [1, 2, 3], "gyro": [4, 5, 6], "age_ms": 1,
         "family": 0},
    ):
        mutated = dict(status)
        mutated["imu"] = {**status["imu"], **bad}
        with pytest.raises(ValueError):
            inspect_status(mutated)


def test_usb_mpu6050_raw_diagnostic_and_family_validation():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"required": True, "ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [40, 40, 40, 40, 250],
                   "age_ms": [10, 10, 10, 10, 10],
                   "present_mask": 31, "valid_mask": 31},
        "imu": {"family": 4, "gyro_id": 0x68, "aux_id": 0,
                "valid": True, "acc": [0, 0, 16384],
                "gyro": [0, 0, -12], "age_ms": 20},
    }
    result = inspect_status(status)
    assert result["imu"]["family"] == "mpu6050"
    assert result["imu"]["raw_six_axis_available"] is True
    assert result["imu"]["attitude_interlock_active"] is False
    assert result["imu"]["physical_qualification_pass"] is False
    for bad in ({"gyro_id": 0}, {"aux_id": 3}, {"family": 5}, {"age_ms": 201}):
        changed = {**status, "imu": {**status["imu"], **bad}}
        with pytest.raises(ValueError):
            inspect_status(changed)


def test_usb_optional_sensor_mask_levels_and_bumper_manual_rearm_gate():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": True, "fault": "none"},
        "ranges": {"mm": [35, 35, 35, 35, 300],
                   "age_ms": [5, 5, 5, 5, 5],
                   "present_mask": 31, "valid_mask": 31},
        "extras": {"mask": 7, "bumper": True, "bumps": 1,
                   "reed": False, "reed_count": 2,
                   "pir": True, "pir_count": 3},
    }
    result = inspect_status(status)
    assert result["optional_inputs"]["enabled_mask"] == 7
    assert result["optional_inputs"]["pir_events"] == 3
    assert result["optional_inputs"]["bumper_events"] == 1
    assert not result["eligible_for_manual_local_rearm"]
    assert not result["optional_inputs"]["physical_qualification_pass"]
    for bad in (
        {"mask": 8}, {"mask": True}, {"bumper": 1}, {"bumps": -1},
        {"reed_count": 2**32}, {"pir": "true"},
    ):
        changed = {**status, "extras": {**status["extras"], **bad}}
        with pytest.raises(ValueError):
            inspect_status(changed)
    changed = {**status, "extras": {**status["extras"], "mask": 0}}
    with pytest.raises(ValueError, match="Unenabled"):
        inspect_status(changed)




def test_usb_extra_left_right_rear_ranges_are_read_only_and_source_checked():
    base = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [50, 50, 50, 50, 200],
                   "age_ms": [1, 1, 1, 1, 1],
                   "present_mask": 31, "valid_mask": 31},
        "side_ranges": {"mm": [310, 295, 0], "age_ms": [6, 7, 0],
                        "present_mask": 3, "valid_mask": 3,
                        "motion_certified": False},
    }
    report = inspect_status(base)
    assert report["side_ranges"]["reported"]
    assert [v["direction"] for v in report["side_ranges"]["readings"]] == [
        "left", "right", "rear",
    ]
    assert report["side_ranges"]["readings"][2]["present"] is False
    assert not report["side_ranges"]["motion_certified"]
    assert not report["side_ranges"]["physical_qualification_pass"]
    for change in (
        {"valid_mask": 7}, {"present_mask": 8}, {"valid_mask": True},
        {"mm": [1, 2]}, {"mm": [0, 20, 0]},
        {"age_ms": [1, -1, 0]}, {"motion_certified": True},
        {"motion_certified": "false"},
    ):
        invalid = {**base, "side_ranges": {**base["side_ranges"], **change}}
        with pytest.raises(ValueError):
            inspect_status(invalid)
    without = dict(base)
    without.pop("side_ranges")
    assert inspect_status(without)["side_ranges"]["reported"] is False

def test_usb_cap1188_eight_touch_zones_are_diagnostic_not_motion_authority():
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [50, 50, 50, 50, 200],
                   "age_ms": [1, 1, 1, 1, 1],
                   "present_mask": 31, "valid_mask": 31},
        "extras": {"mask": 0, "bumper": False, "bumps": 0,
                   "reed": False, "reed_count": 0,
                   "pir": False, "pir_count": 0,
                   "cap": 0b10000001, "cap_ok": True, "cap_events": 7},
    }
    report = inspect_status(status)
    assert report["cap_touch"]["zone_mask"] == 129
    assert report["cap_touch"]["rising_zone_events"] == 7
    assert report["cap_touch"]["valid"]
    assert not report["cap_touch"]["physical_qualification_pass"]
    # Optional petting never grants nor revokes local USB safety recovery.
    # The diagnostic must be identical to an otherwise identical body status
    # with CAP fields absent. Actual WROOM guard remains authoritative.
    without_cap = {
        **status, "extras": {
            key: value for key, value in status["extras"].items()
            if key not in ("cap", "cap_ok", "cap_events")
        },
    }
    assert (report["eligible_for_manual_local_rearm"] ==
            inspect_status(without_cap)["eligible_for_manual_local_rearm"])
    for broken in (
        {"cap": 256}, {"cap": -1}, {"cap": True},
        {"cap_ok": 1}, {"cap_events": -2},
        {"cap_events": 2**32},
        {"cap": 1, "cap_ok": False},
    ):
        corrupted = {**status, "extras": {**status["extras"], **broken}}
        with pytest.raises(ValueError):
            inspect_status(corrupted)
    incomplete = {**status, "extras": {key: value for key, value
                                     in status["extras"].items()
                                     if key != "cap_events"}}
    with pytest.raises(ValueError):
        inspect_status(incomplete)

@pytest.mark.parametrize("change", [
    {"backend": "dc_pwm"},
    {"imu": {"family": 5, "gyro_id": 0, "aux_id": 0}},
    {"imu": {"family": 4, "gyro_id": 0, "aux_id": 0}},
    {"imu": {"family": True, "gyro_id": 212, "aux_id": 73}},
    {"touch": {"active": "false"}},
    {"safety": None},
    {"ranges": {}},
    {"ranges": {"mm": [1] * 5, "age_ms": [1] * 5,
                "present_mask": True, "valid_mask": 31}},
    {"ranges": {"mm": [1] * 5, "age_ms": [1] * 5,
                "present_mask": 63, "valid_mask": 31}},
    {"ranges": {"mm": [1, 2, 3], "age_ms": [1] * 5,
                "present_mask": 31, "valid_mask": 31}},
])
def test_usb_bench_rejects_malformed_or_wrong_profile_status(change):
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "missing_sample"},
        "ranges": {"mm": [50, 50, 50, 50, 200],
                   "age_ms": [2, 2, 2, 2, 2],
                   "present_mask": 31, "valid_mask": 31},
    }
    status.update(change)
    with pytest.raises(ValueError):
        inspect_status(status)
