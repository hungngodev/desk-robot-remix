"""Side-range capture uses actual WROOM conversion identity without motion."""
from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "scripts"
capture = runpy.run_path(str(ROOT / "capture_side_ranges.py"))
capture_phase = capture["capture_phase"]
status_url = capture["_status_url"]
analyze = runpy.run_path(str(ROOT / "calibrate_side_ranges.py"))["analyze"]


def frame(sample_ms=100, *, side="left", mm=80, boot=73, robot="robot-01",
          armed=False, age=10):
    index = {"left": 0, "right": 1, "rear": 2}[side]
    distances, stamps = [800, 800, 800], [0, 0, 0]
    distances[index], stamps[index] = mm, sample_ms
    return {
        "robot_id": robot, "armed": armed,
        "motor": {"m0": 0, "m1": 0}, "drive_ms": 0,
        "side_ranges": {
            "mm": distances, "age_ms": [age, age, age],
            "sample_ms": stamps, "boot_id": boot,
            "present_mask": 7, "valid_mask": 7,
            "motion_certified": False,
        },
    }


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, frames):
        self.frames, self.requests = frames, []

    async def get(self, url, *, headers, timeout):
        self.requests.append((url, headers, timeout))
        return FakeResponse(
            self.frames[min(len(self.requests) - 1, len(self.frames) - 1)]
        )


async def get(client, *, side="left", label="near", count=1,
              previous_ms=None, previous_boot=None, sample_id_start=1):
    return await capture_phase(
        client, base_url="http://127.0.0.1:8008", robot="robot-01",
        token="operator-private-demo-token", side=side, label=label,
        count=count, interval=.05, sample_id_start=sample_id_start,
        firmware_commit="physically-flashed-sha", mount_id="chassis-mount-a",
        previous_ms=previous_ms, previous_boot=previous_boot,
    )


async def test_only_authenticated_read_only_status_is_used_for_real_conversions():
    client = FakeClient([frame(100), frame(130)])
    rows = await get(client, count=2)
    assert [r["side_ranges"]["sample_ms"][0] for r in rows] == [100, 130]
    assert [r["sample_id"] for r in rows] == [1, 2]
    assert all(r["firmware_commit"] == "physically-flashed-sha" for r in rows)
    assert all(r["mount_id"] == "chassis-mount-a" for r in rows)
    assert all(u.endswith("/v1/robots/robot-01/status")
               for u, _, _ in client.requests)
    assert all(h == {"Authorization": "Bearer operator-private-demo-token"}
               for _, h, _ in client.requests)


@pytest.mark.parametrize("bad,reason", [
    (frame(robot="robot-02"), "robot identity"),
    (frame(armed=True), "Disarm"),
    (frame(age=400), "Invalid"),
    ({**frame(), "drive_ms": 300}, "Disarm"),
    ({**frame(), "motor": {"m0": 60, "m1": 0}}, "Disarm"),
    ({**frame(), "side_ranges": None}, "side_ranges"),
])
async def test_wrong_robot_motion_or_stale_sensor_is_rejected(bad, reason):
    with pytest.raises(RuntimeError, match=reason):
        await get(FakeClient([bad]))


async def test_duplicate_http_reads_do_not_count_as_independent_toF_samples():
    client = FakeClient([frame(100)])
    with pytest.raises(RuntimeError, match="Not enough distinct"):
        await get(client, count=2)
    assert len(client.requests) == 20


async def test_uint32_rollover_accepted_but_pre_wrap_replay_rejected():
    rows = await get(
        FakeClient([frame(0xffffffff), frame(2)]),
        count=2, previous_ms=0xfffffffe, previous_boot=73,
    )
    assert [r["side_ranges"]["sample_ms"][0] for r in rows] == [
        0xffffffff, 2,
    ]
    with pytest.raises(RuntimeError, match="Replayed or reversed"):
        await get(
            FakeClient([frame(0xffffffff)]),
            previous_ms=2, previous_boot=73,
        )


async def test_wroom_boot_change_cannot_be_mixed_into_one_trial():
    with pytest.raises(RuntimeError, match="reboot"):
        await get(FakeClient([frame(120, boot=74)]), previous_boot=73)


@pytest.mark.parametrize("url,robot", [
    ("http://example.com:8008", "robot-01"),
    ("http://192.168.0.2:8008", "robot-01"),
    ("http://localhost:8008/api", "robot-01"),
    ("http://user:pass@localhost:8008", "robot-01"),
    ("http://localhost:8008/?token=bad", "robot-01"),
    ("http://localhost:8008", "../robot-02"),
    ("http://localhost:8008", "robot-01/stop"),
])
def test_token_is_never_sent_to_untrusted_public_http_or_raw_model_path(url, robot):
    with pytest.raises(ValueError):
        status_url(url, robot)


def test_fixed_private_mac_status_endpoint():
    assert status_url("http://127.0.0.1:8008", "robot-01") == (
        "http://127.0.0.1:8008/v1/robots/robot-01/status"
    )
    assert status_url("https://private.example", "robot-01").endswith(
        "/v1/robots/robot-01/status"
    )


async def test_six_real_capture_phases_feed_existing_analyzer_without_permission():
    rows, previous = [], {}
    for side in ("left", "right", "rear"):
        for label in ("near", "far"):
            for n in range(20):
                stamp = (n + (20 if label == "far" else 0) + 1) * 25
                distance = 80 + n if label == "near" else 500 + n
                phase = await get(
                    FakeClient([frame(stamp, side=side, mm=distance)]),
                    side=side, label=label, sample_id_start=len(rows) + 1,
                    previous_ms=previous.get(side), previous_boot=73,
                )
                rows.extend(phase)
                previous[side] = stamp
    verdict = analyze(rows, "robot-01")
    assert verdict["samples_total"] == 120
    assert verdict["physical_acceptance_pass"] is False
    assert verdict["independent_sample_provenance_verified"] is False
    assert verdict["no_motion_authority"] is True


@pytest.mark.parametrize("invalid", [None, True, -1, 0x100000000])
async def test_invalid_sensor_clock_or_missing_boot_identity_rejected(invalid):
    bad = frame()
    bad["side_ranges"]["sample_ms"][0] = invalid
    with pytest.raises(RuntimeError, match="Invalid"):
        await get(FakeClient([bad]))
    bad = frame()
    bad["side_ranges"]["boot_id"] = invalid
    with pytest.raises(RuntimeError, match="Invalid"):
        await get(FakeClient([bad]))
