"""Side-range capture uses actual WROOM conversion identity without motion."""
from __future__ import annotations

import json
import os
import runpy
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "scripts"
capture = runpy.run_path(str(ROOT / "capture_side_ranges.py"))
capture_phase = capture["capture_phase"]
status_url = capture["_status_url"]
preflight_private_output = capture["preflight_private_output"]
write_private_rows = capture["write_private_rows"]
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


def test_side_trial_output_is_exclusive_private_and_consumable(tmp_path):
    output_path = tmp_path / "side_ranges.jsonl"
    rows = [{"robot_id": "robot-01", "sample_id": 1}]
    original_parent = preflight_private_output(output_path)
    old_umask = os.umask(0)
    try:
        write_private_rows(output_path, rows, expected_parent=original_parent)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert [json.loads(line) for line in output_path.read_text().splitlines()] == rows
    with pytest.raises(FileExistsError):
        preflight_private_output(output_path)
    with pytest.raises(FileExistsError):
        write_private_rows(output_path, [{"sample_id": 2}], expected_parent=original_parent)
    assert [json.loads(line) for line in output_path.read_text().splitlines()] == rows


def test_side_trial_preflight_rejects_symlinked_previous_report(tmp_path):
    evidence = tmp_path / "previous.jsonl"
    evidence.write_text("private original")
    alias = tmp_path / "new.jsonl"
    alias.symlink_to(evidence)
    with pytest.raises(FileExistsError):
        preflight_private_output(alias)
    # Use a valid lease from this exact folder. An invalid inode lease
    # correctly fails earlier, before O_EXCL can check the linked report.
    expected_parent = preflight_private_output(tmp_path / "unused-report.jsonl")
    with pytest.raises(FileExistsError):
        write_private_rows(
            alias, [{"sample_id": 3}], expected_parent=expected_parent,
        )
    assert not (tmp_path / "unused-report.jsonl").exists()
    assert evidence.read_text() == "private original"


def test_side_trial_capture_never_follows_user_controlled_directory_alias(tmp_path):
    secure = tmp_path / "actual"
    secure.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(secure, target_is_directory=True)
    candidate = alias / "forged.jsonl"
    with pytest.raises(ValueError, match="symlink"):
        preflight_private_output(candidate)
    with pytest.raises(ValueError, match="symlink"):
        write_private_rows(candidate, [{"sample_id": 1}], expected_parent=(0, 0))
    assert not (secure / "forged.jsonl").exists()


def test_side_trial_capture_requires_private_parent_and_refuses_traversal(tmp_path):
    public = tmp_path / "shared"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(ValueError, match="private mode"):
        preflight_private_output(public / "new.jsonl")
    with pytest.raises(ValueError, match="private mode"):
        write_private_rows(public / "new.jsonl", [], expected_parent=(0, 0))
    assert not (public / "new.jsonl").exists()
    with pytest.raises(ValueError, match="traversal"):
        preflight_private_output(tmp_path / "shared" / ".." / "new.jsonl")


def test_physical_side_capture_refuses_swapped_private_destination(tmp_path):
    approved = tmp_path / "operator-private"
    approved.mkdir(mode=0o700)
    destination = approved / "measured.jsonl"
    identity = preflight_private_output(destination)

    # The data collection awaits 120 sensor conversions and 6 operator
    # prompts; do not let a replaced output folder receive private evidence.
    approved.rename(tmp_path / "former-private")
    approved.mkdir(mode=0o700)
    replacement = approved / "measured.jsonl"
    with pytest.raises(RuntimeError, match="changed since preflight"):
        write_private_rows(
            replacement, [{"robot_id": "robot-01", "sample_id": 1}],
            expected_parent=identity,
        )
    assert not replacement.exists()
    assert not (tmp_path / "former-private" / "measured.jsonl").exists()


def test_private_side_capture_requires_real_preflight_identity(tmp_path):
    output = tmp_path / "side.jsonl"
    with pytest.raises(RuntimeError, match="changed since preflight"):
        write_private_rows(output, [], expected_parent=(0, 0))
    assert not output.exists()


async def test_side_capture_main_ignores_ambient_proxy_and_keeps_private_output(
    monkeypatch, tmp_path,
):
    # Exercise the real operator CLI construction, without an actual robot.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7890")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setenv("DESK_ROBOT_API_TOKEN", "operator-private-demo-token")
    output = tmp_path / "side-physical-provenance.jsonl"
    monkeypatch.setattr(sys, "argv", [
        "capture_side_ranges.py", "--robot", "robot-01",
        "--firmware-commit", "flash-sha", "--mount-id", "measured-mount",
        "--output", str(output),
    ])
    monkeypatch.setattr("builtins.input", lambda _: "")
    recorded = {}
    main = capture["main"]

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def client_factory(**kwargs):
        recorded.update(kwargs)
        return Client()

    async def fake_capture_phase(client, **kwargs):
        assert isinstance(client, Client)
        assert kwargs["token"] == "operator-private-demo-token"
        assert kwargs["robot"] == "robot-01"
        assert kwargs["count"] == 20
        return [{
            "robot_id": kwargs["robot"], "direction": kwargs["side"],
            "label": kwargs["label"], "sample_id": kwargs["sample_id_start"],
            "side_ranges": {"boot_id": 73, "sample_ms": [100, 200, 300]},
        }]

    monkeypatch.setattr(main.__globals__["httpx"], "AsyncClient", client_factory)
    monkeypatch.setitem(main.__globals__, "capture_phase", fake_capture_phase)
    await main()
    assert recorded == {"trust_env": False, "follow_redirects": False}
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert [(row["direction"], row["label"]) for row in rows] == list(
        capture["PHASES"]
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o600



@pytest.mark.parametrize("side", ["left", "right", "rear"])
@pytest.mark.parametrize("distance", [1, 29, 1301])
async def test_capture_rejects_outside_production_range(side, distance):
    with pytest.raises(RuntimeError, match="Invalid"):
        await get(FakeClient([frame(side=side, mm=distance)]), side=side)


@pytest.mark.parametrize("side", ["left", "right", "rear"])
@pytest.mark.parametrize("distance", [30, 1300])
async def test_capture_preserves_selected_lens_at_valid_range_boundaries(side, distance):
    rows = await get(FakeClient([frame(side=side, mm=distance)]), side=side)
    index = {"left": 0, "right": 1, "rear": 2}[side]
    assert rows[0]["side_ranges"]["mm"][index] == distance


async def test_capture_records_request_age_and_operator_surface_condition(monkeypatch):
    ticks = iter([10.0, 10.125])
    monkeypatch.setitem(capture_phase.__globals__, "time", type(
        "Clock", (), {"monotonic": staticmethod(lambda: next(ticks))},
    ))
    rows = await capture_phase(
        FakeClient([frame(age=225)]), base_url="http://127.0.0.1:8008",
        robot="robot-01", token="operator-private-demo-token", side="left",
        label="near", count=1, interval=.05, sample_id_start=1,
        firmware_commit=" flash-sha ", mount_id=" mount-a ",
        surface_condition=" matte black, indoor lighting ",
    )
    assert rows[0]["request_elapsed_ms"] == 125
    assert rows[0]["captured_at_monotonic_s"] == 10.125
    assert rows[0]["side_ranges"]["age_ms"][0] == 225
    assert rows[0]["firmware_commit"] == "flash-sha"
    assert rows[0]["mount_id"] == "mount-a"
    assert rows[0]["surface_condition"] == "matte black, indoor lighting"
