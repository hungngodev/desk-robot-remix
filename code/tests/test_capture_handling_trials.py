"""Read-only physical MPU trial recorder never controls actuators."""
from __future__ import annotations

import runpy
from pathlib import Path

import pytest

_capture_module = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/capture_handling_trials.py"
))
capture_phase = _capture_module["capture_phase"]
_safe_endpoint = _capture_module["_safe_endpoint"]


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, *, wrong_robot=False, moving=False,
                 repeated=False, bad_imu=False, reboot=False):
        self.calls = []
        self.count = 0
        self.wrong_robot = wrong_robot
        self.moving = moving
        self.repeated = repeated
        self.bad_imu = bad_imu
        self.reboot = reboot

    async def get(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        self.count += 1
        return FakeResponse({
            "robot_id": "robot-02" if self.wrong_robot else "robot-01",
            "motor": {"m0": 20 if self.moving else 0, "m1": 0},
            "drive_ms": 0,
            "imu": {
                "family": 4, "gyro_id": 104, "valid": not self.bad_imu,
                "age_ms": 20, "sample_ms": 1 if self.repeated else self.count,
                "boot_id": 2 if self.reboot else 1,
                "acc": [0, 0, 16384], "gyro": [0, 0, 0],
            },
        })


async def read(client, *, count=2, previous_sample=None, previous_boot=None):
    return await capture_phase(
        client, base_url="http://127.0.0.1:8008", robot="robot-01",
        token="operator-valid-token", label="upright", count=count,
        sample_interval=0.05, firmware_commit="sha",
        mount_id="mount-1", previous_sample=previous_sample,
        previous_boot=previous_boot,
    )


async def test_real_telemetry_capture_preserves_identity_and_fresh_conversion():
    client = FakeClient()
    rows = await read(client)
    assert len(rows) == 2
    assert [row["body"]["imu"]["sample_ms"] for row in rows] == [1, 2]
    assert all(row["firmware_commit"] == "sha" for row in rows)
    assert all(row["mount_id"] == "mount-1" for row in rows)
    assert all(row["label"] == "upright" for row in rows)
    assert all(path.endswith("/v1/robots/robot-01/status")
               for path, _, _ in client.calls)
    assert all(headers == {"Authorization": "Bearer operator-valid-token"}
               for _, headers, _ in client.calls)


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"wrong_robot": True}, "robot identity"),
    ({"moving": True}, "moving"),
    ({"bad_imu": True}, "invalid"),
])
async def test_wroom_capture_fails_closed_on_wrong_or_invalid_source(
    kwargs, message,
):
    with pytest.raises(RuntimeError, match=message):
        await read(FakeClient(**kwargs), count=1)


async def test_reboot_can_never_be_mixed_into_one_mount_trial():
    with pytest.raises(RuntimeError, match="reboot"):
        await read(FakeClient(reboot=True), count=1, previous_boot=1)


async def test_duplicate_cached_frame_never_becomes_another_measurement():
    with pytest.raises(RuntimeError, match="fresh independent"):
        await read(FakeClient(repeated=True), count=2)


@pytest.mark.parametrize("url,robot", [
    ("http://example.com:8008", "robot-01"),
    ("http://192.168.0.2:8008", "robot-01"),
    ("http://localhost:8008/api", "robot-01"),
    ("http://user:pass@localhost:8008", "robot-01"),
    ("http://localhost:8008/?secret=yes", "robot-01"),
    ("http://localhost:8008", "../robot-02"),
    ("http://localhost:8008", "robot-01/stop"),
])
def test_operator_token_never_sent_to_untrusted_http_or_ambiguous_robot(url, robot):
    with pytest.raises(ValueError):
        _safe_endpoint(url, robot)


def test_authenticated_local_capture_path_rejects_no_valid_pets():
    assert _safe_endpoint("http://127.0.0.1:8008", "robot-01").endswith(
        "/v1/robots/robot-01/status",
    )
    assert _safe_endpoint("https://my-robot-mac.example:8008", "robot-01").endswith(
        "/v1/robots/robot-01/status",
    )
