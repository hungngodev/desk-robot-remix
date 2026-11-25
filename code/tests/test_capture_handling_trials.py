"""Read-only physical MPU trial recorder never controls actuators."""
from __future__ import annotations

import json
import os
import runpy
import stat
from pathlib import Path

import httpx
import pytest

_capture_module = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/capture_handling_trials.py"
))
capture_phase = _capture_module["capture_phase"]
_safe_endpoint = _capture_module["_safe_endpoint"]
_operator_status_client = _capture_module["_operator_status_client"]
save_private_trial_rows = _capture_module["save_private_trial_rows"]


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self, **kwargs):
        return json.loads(json.dumps(self.data), **kwargs)


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


class SequencedFakeClient(FakeClient):
    """Return exact WROOM conversion counters across a uint32 rollover."""

    def __init__(self, counters):
        super().__init__()
        self.counters = counters

    async def get(self, url, *, headers, timeout):
        response = await super().get(url, headers=headers, timeout=timeout)
        index = min(self.count - 1, len(self.counters) - 1)
        response.data["imu"]["sample_ms"] = self.counters[index]
        return response


async def test_capture_accepts_same_boot_uint32_wrap_within_and_across_phases():
    rows = await read(
        SequencedFakeClient([0xfffffffe, 0xffffffff, 0, 1]), count=4,
    )
    assert [row["body"]["imu"]["sample_ms"] for row in rows] == [
        0xfffffffe, 0xffffffff, 0, 1,
    ]
    # A labelled phase begins after an operator prompt, but retains the same
    # real WROOM boot identity and source conversion cursor.
    next_phase = await read(
        SequencedFakeClient([0]), count=1,
        previous_sample=0xffffffff, previous_boot=1,
    )
    assert next_phase[0]["body"]["imu"]["sample_ms"] == 0


async def test_capture_rejects_delayed_pre_wrap_replay_after_wrap():
    # A delayed older conversion has a numerically larger timestamp than
    # the already accepted post-wrap value. Only the new value 3 is legal.
    rows = await read(
        SequencedFakeClient([0xffffffff, 3]), count=1,
        previous_sample=2, previous_boot=1,
    )
    assert rows[0]["body"]["imu"]["sample_ms"] == 3


async def test_capture_never_counts_only_pre_wrap_replays_as_fresh():
    with pytest.raises(RuntimeError, match="fresh independent"):
        await read(
            SequencedFakeClient([0xffffffff]), count=1,
            previous_sample=2, previous_boot=1,
        )


def test_measured_trial_output_is_exclusive_and_mode_0600(tmp_path):
    output = tmp_path / "handling.jsonl"
    rows = [{"label": "upright", "body": {"imu": {"sample_ms": 4}}}]
    old_umask = os.umask(0o022)
    try:
        save_private_trial_rows(output, rows)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert [json.loads(line) for line in output.read_text().splitlines()] == rows
    with pytest.raises(FileExistsError):
        save_private_trial_rows(output, rows)
    assert [json.loads(line) for line in output.read_text().splitlines()] == rows


def test_measured_trial_output_rejects_symlink_and_invalid_rows(tmp_path):
    actual = tmp_path / "existing.jsonl"
    actual.write_text("original evidence\n", encoding="utf-8")
    redirected = tmp_path / "redirected.jsonl"
    redirected.symlink_to(actual)
    with pytest.raises(FileExistsError):
        save_private_trial_rows(redirected, [{"body": "should not write"}])
    assert actual.read_text(encoding="utf-8") == "original evidence\n"
    invalid = tmp_path / "invalid.jsonl"
    with pytest.raises(TypeError):
        save_private_trial_rows(invalid, [{"unserializable": object()}])
    assert not invalid.exists()
    with pytest.raises(ValueError, match="No captured IMU samples"):
        save_private_trial_rows(invalid, [])
    assert not invalid.exists()

def test_measured_trial_rejects_symlinked_output_parent(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="parent must not be a symlink"):
        save_private_trial_rows(alias / "handling.jsonl", [{"label": "upright"}])
    assert list(actual.iterdir()) == []


def test_measured_trial_parent_replacement_cleans_original_directory(
    tmp_path, monkeypatch,
):
    parent = tmp_path / "parent"
    parent.mkdir()
    displaced = tmp_path / "displaced"
    redirect = tmp_path / "redirect"
    redirect.mkdir()
    real_open = os.open
    replaced = False

    def swap_parent_on_file_create(path, flags, *args, **kwargs):
        nonlocal replaced
        if (path == "handling.jsonl" and kwargs.get("dir_fd") is not None
                and not replaced):
            replaced = True
            parent.rename(displaced)
            parent.symlink_to(redirect, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_parent_on_file_create)
    with pytest.raises(ValueError, match="output parent changed"):
        save_private_trial_rows(
            parent / "handling.jsonl", [{"label": "upright"}],
        )
    assert replaced
    assert list(displaced.iterdir()) == []
    assert list(redirect.iterdir()) == []

def test_operator_status_client_does_not_use_environment_proxies(
    monkeypatch,
):
    # HTTPX defaults to trust_env=True; with HTTP_PROXY present a loopback
    # HTTP bearer can be sent through an unrelated proxy unless disabled.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.delenv("NO_PROXY", raising=False)
    observed = {}

    def client_factory(**kwargs):
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(_capture_module["httpx"], "AsyncClient", client_factory)
    _operator_status_client()
    assert observed == {"trust_env": False, "follow_redirects": False}


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    [
        ('"robot_id": "robot-01"', '"robot_id": "robot-02", "robot_id": "robot-01"',
         "Duplicate WROOM status JSON field: robot_id"),
        ('"boot_id": 1', '"boot_id": 2, "boot_id": 1',
         "Duplicate WROOM status JSON field: boot_id"),
        ('"age_ms": 20', '"age_ms": NaN',
         "Nonfinite WROOM status JSON constant: NaN"),
    ],
)
async def test_capture_rejects_ambiguous_wire_json(original, replacement, message):
    class RawStatusClient(FakeClient):
        async def get(self, url, *, headers, timeout):
            response = await super().get(url, headers=headers, timeout=timeout)
            payload = json.dumps(response.data)
            assert payload.count(original) == 1
            return httpx.Response(
                200, content=payload.replace(original, replacement),
                request=httpx.Request("GET", url),
            )

    with pytest.raises(ValueError, match=message):
        await read(RawStatusClient(), count=1)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_private_trial_output_rejects_nonfinite_values(tmp_path, value):
    output = tmp_path / "trial.jsonl"
    with pytest.raises(ValueError, match="Out of range float values"):
        save_private_trial_rows(output, [{"body": {"extra": value}}])
    assert not output.exists()


class NativeLowGClient(FakeClient):
    async def get(self, url, *, headers, timeout):
        response = await super().get(url, headers=headers, timeout=timeout)
        response.data["imu"].update(
            low_g_valid=True, low_g_irq=False, low_g_seq=self.count + 2,
        )
        return response


async def test_capture_rejects_intervening_native_low_g_event():
    with pytest.raises(RuntimeError, match="low-g"):
        await read(NativeLowGClient())


async def test_capture_rejects_native_low_g_event_between_phases():
    with pytest.raises(RuntimeError, match="low-g"):
        await capture_phase(
            NativeLowGClient(), base_url="http://127.0.0.1:8008", robot="robot-01",
            token="operator-valid-token", label="tilted", count=1,
            sample_interval=0.05, firmware_commit="sha", mount_id="mount-1",
            previous_sample=0, previous_boot=1,
            previous_imu={"low_g_valid": True, "low_g_irq": False, "low_g_seq": 2},
        )
