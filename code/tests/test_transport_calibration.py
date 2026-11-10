import json
from pathlib import Path
from runpy import run_path

import httpx
import pytest
from desk_robot.calibration import Calibration
from desk_robot.transport import HeadError, HttpHead, validate_command

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
    assert result["imu"]["motion_driver_active"] is False
    assert result["local_guard_fault"] == "missing_sample"
    assert not result["physical_qualification_pass"]
    status["ranges"]["present_mask"] = 23
    status["ranges"]["valid_mask"] = 15
    result = inspect_status(status)
    assert not result["ranges"][3]["present"]
    assert not result["ranges"][4]["valid"]
    assert not result["eligible_for_manual_local_rearm"]


@pytest.mark.parametrize("change", [
    {"backend": "dc_pwm"},
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
