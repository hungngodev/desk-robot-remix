"""Read-only dual RMT IR receiver field log must not forge movement."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "terminal_ir_calibrator", ROOT / "code/scripts/calibrate_terminal_ir.py"
)
cal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cal)


def position_records():
    rows = []
    left_seq = right_seq = 0
    now = 1000.0
    for label in ("left", "center", "right"):
        for _ in range(20):
            left_seen = label in ("left", "center")
            r = label in ("center", "right")
            if left_seen:
                left_seq += 1
            if r:
                right_seq += 1
            rows.append({
                "label": label, "received_monotonic": now,
                "ir": {
                    "robot_id": "robot-01", "left_valid": left_seen,
                    "right_valid": r, "match": left_seen and r,
                    "left_seq": left_seq, "right_seq": right_seq,
                    "left_age_ms": 20 if left_seen else 0xffffffff,
                    "right_age_ms": 20 if r else 0xffffffff,
                    "code": 0xCB34ED12 if left_seen and r else 0,
                    "motor_authorized": False,
                    "charging_authorized": False,
                    "physical_qualified": False,
                },
            })
            now += .25
    return rows


def test_labeled_signal_rate_detects_candidate_not_steering_calibration():
    result = cal.analyze(position_records(), "robot-01")
    assert result["observations_total"] == 60
    assert result["candidate_differential_signal"] is True
    assert result["physical_acceptance_pass"] is False
    assert result["absolute_bearing_calibrated"] is False
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False


def test_forged_valid_sample_without_new_rmt_frame_is_not_optical_evidence():
    rows = position_records()
    rows[1]["ir"]["left_seq"] = rows[0]["ir"]["left_seq"]
    with pytest.raises(ValueError, match="Replayed"):
        cal.analyze(rows, "robot-01")


@pytest.mark.parametrize("mutation", [
    lambda r: r[1].update(received_monotonic=r[0]["received_monotonic"]),
    lambda r: r[0]["ir"].update(charging_authorized=True),
    lambda r: r[0]["ir"].update(robot_id="robot-02"),
    lambda r: r[0].update(label="unmeasured"),
])
def test_untrustworthy_receiver_trial_is_rejected(mutation):
    rows = position_records()
    mutation(rows)
    with pytest.raises(ValueError):
        cal.analyze(rows, "robot-01")


def test_unbalanced_optics_cannot_be_sold_as_differential_bearing():
    rows = position_records()
    # All signal samples from all locations appear identical. RMT frame
    # sequences still legitimately advance, but baffles tell us nothing.
    for n, row in enumerate(rows, 1):
        row["ir"].update(
            left_valid=True, right_valid=True, match=True,
            left_seq=n, right_seq=n, code=0xCB34ED12,
            left_age_ms=15, right_age_ms=15,
        )
    result = cal.analyze(rows, "robot-01")
    assert result["candidate_differential_signal"] is False


async def test_capture_uses_authenticated_mac_read_only_ir_endpoint(monkeypatch):
    monkeypatch.setattr(cal.asyncio, "sleep", fast_sleep)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v1/robots/robot-01/dock/ir"
        assert request.headers["Authorization"] == "Bearer " + "S" * 40
        data = position_records()[0]["ir"]
        data["left_seq"] += len(calls)
        return httpx.Response(200, json=data)

    actual = httpx.AsyncClient

    def create_client(*args, **kwargs):
        return actual(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cal.httpx, "AsyncClient", create_client)
    rows = await cal.capture(
        "http://localhost:8765", "S" * 40, "robot-01",
        "left", 20, .05,
    )
    assert len(calls) == 20
    assert len(rows) == 20
    assert all(row["ir"]["charging_authorized"] is False for row in rows)


async def fast_sleep(_seconds):
    return None


@pytest.mark.parametrize(("optical_age_ms", "roundtrip_s"), [
    (185, .020),  # Head age plus transport delay exceeds 200 ms.
    (20, .210),  # Even a young frame expires during a long HTTP response.
])
async def test_capture_rejects_http_delay_that_expires_optical_evidence(
    monkeypatch, optical_age_ms, roundtrip_s,
):
    monkeypatch.setattr(cal.asyncio, "sleep", fast_sleep)
    calls = []

    def handler(request):
        calls.append(request)
        sample = position_records()[0]["ir"].copy()
        sample["left_age_ms"] = optical_age_ms
        return httpx.Response(200, json=sample)

    original_client = httpx.AsyncClient

    def create_client(*args, **kwargs):
        return original_client(
            *args, transport=httpx.MockTransport(handler), **kwargs,
        )

    monkeypatch.setattr(cal.httpx, "AsyncClient", create_client)
    moments = iter((1000.0, 1000.0 + roundtrip_s))
    # Rebind this script's clock only; do not alter asyncio's global clock.
    monkeypatch.setattr(
        cal, "time", SimpleNamespace(monotonic=lambda: next(moments)),
    )
    with pytest.raises(ValueError, match="Delayed terminal IR HTTP response"):
        await cal.capture(
            "http://localhost:8765", "S" * 40, "robot-01", "left", 20, .05,
        )
    assert len(calls) == 1


async def test_capture_accepts_fast_delivery_inside_optical_age_budget(monkeypatch):
    monkeypatch.setattr(cal.asyncio, "sleep", fast_sleep)
    calls = []

    def handler(request):
        calls.append(request)
        sample = position_records()[0]["ir"].copy()
        sample["left_seq"] = len(calls)
        sample["left_age_ms"] = 180
        return httpx.Response(200, json=sample)

    original_client = httpx.AsyncClient

    def create_client(*args, **kwargs):
        return original_client(
            *args, transport=httpx.MockTransport(handler), **kwargs,
        )

    monkeypatch.setattr(cal.httpx, "AsyncClient", create_client)
    ticks = [0]

    def clock():
        index, phase = divmod(ticks[0], 2)
        ticks[0] += 1
        return 1000.0 + index + (.019 if phase else 0.0)

    monkeypatch.setattr(cal, "time", SimpleNamespace(monotonic=clock))
    rows = await cal.capture(
        "http://localhost:8765", "S" * 40, "robot-01", "left", 20, .05,
    )
    assert len(calls) == len(rows) == 20
    assert rows[0]["received_monotonic"] == pytest.approx(1000.019)
    assert rows[-1]["ir"]["left_seq"] == 20



def test_labeled_trial_rejects_dock_from_another_physical_robot():
    rows = position_records()  # robot 01 currently observes dock 04
    assert cal.analyze(rows, "robot-01", expected_dock_id=4)[
        "candidate_differential_signal"
    ]
    with pytest.raises(ValueError, match="Foreign NEC dock beacon"):
        cal.analyze(rows, "robot-01", expected_dock_id=1)


async def test_capture_rejects_foreign_assigned_dock_at_http_boundary(monkeypatch):
    monkeypatch.setattr(cal.asyncio, "sleep", fast_sleep)
    calls = []

    def handler(request):
        calls.append(request)
        frame = position_records()[20]["ir"]  # both sides fresh, dock 04
        return httpx.Response(200, json=frame)

    actual = httpx.AsyncClient

    def create_client(*args, **kwargs):
        return actual(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cal.httpx, "AsyncClient", create_client)
    with pytest.raises(ValueError, match="Foreign NEC dock beacon"):
        await cal.capture("http://localhost:8765", "S" * 40,
                          "robot-01", "center", 20, .05, 1)
    assert len(calls) == 1


def test_cached_one_sided_rmt_frame_does_not_count_twenty_left_optical_votes():
    """Right-only new frames cannot turn one cached left vote into twenty."""
    rows = position_records()
    for i, row in enumerate(rows[:20], 1):
        row["ir"].update(
            left_seq=10, right_seq=i,
            left_valid=True, right_valid=True,
            left_age_ms=15, right_age_ms=15,
            match=False, code=0,
        )
    for row in rows[20:]:
        if row["ir"]["right_seq"]:
            row["ir"]["right_seq"] += 20
    result = cal.analyze(rows, "robot-01")
    assert result["positions"]["left"]["left_fresh_count"] == 1
    assert result["positions"]["left"]["left_fresh_fraction"] == .05
    assert result["positions"]["left"]["right_fresh_count"] == 20
    assert result["independent_fresh_minimum_met"] is False
    assert result["candidate_differential_signal"] is False


def test_center_pair_requires_two_independently_advancing_frame_counters():
    """Matching code with only one advancing side is not a fresh optical pair."""
    rows = position_records()
    for row in rows[20:40]:
        row["ir"]["right_seq"] = 1
        assert row["ir"]["match"] is True
    result = cal.analyze(rows, "robot-01")
    center = result["positions"]["center"]
    assert center["left_fresh_count"] == 20
    assert center["right_fresh_count"] == 1
    assert center["both_matching_count"] == 1
    assert center["both_matching_fraction"] == .05
    assert result["candidate_differential_signal"] is False


def test_true_32bit_receiver_counter_rollover_is_fresh_optical_evidence():
    rows = position_records()
    rows[0]["ir"]["left_seq"] = 0xfffffffe
    rows[1]["ir"]["left_seq"] = 0xffffffff
    rows[2]["ir"]["left_seq"] = 1
    result = cal.analyze(rows, "robot-01")
    assert result["positions"]["left"]["left_fresh_count"] == 20
    assert result["independent_fresh_minimum_met"] is True
    assert result["candidate_differential_signal"] is True


def test_rebooted_receiver_counter_still_requires_restart_of_trial():
    rows = position_records()
    rows[1]["ir"]["left_seq"] = 0xffffffff
    with pytest.raises(ValueError, match="Reboot or out-of-order"):
        cal.analyze(rows, "robot-01")


def test_mixed_dock_codes_in_center_records_rejected():
    rows = position_records()
    # Alternate center records between dock 4 (0xCB34ED12) and dock 5 (0xCA35ED12)
    for i in range(21, 40, 2):
        rows[i]["ir"]["code"] = 0xCA35ED12
    with pytest.raises(ValueError, match="Mixed NEC dock beacons in trial"):
        cal.analyze(rows, "robot-01")


def test_analyze_reports_assigned_dock_identity():
    rows = position_records()
    # Explicit expected_dock_id
    res_assigned = cal.analyze(rows, "robot-01", expected_dock_id=4)
    assert res_assigned["assigned_dock_id"] == 4
    assert res_assigned["dock_id_assigned"] is True

    # Inferred from observed matching beacon code without explicit assignment
    res_inferred = cal.analyze(rows, "robot-01")
    assert res_inferred["assigned_dock_id"] == 4
    assert res_inferred["dock_id_assigned"] is False


def test_cli_requires_dock_id_for_both_capture_and_input(monkeypatch, tmp_path, capsys):
    dummy_input = tmp_path / "trial.jsonl"
    dummy_input.write_text(json.dumps(position_records()[0]) + "\n")

    # Missing --dock-id with --input
    monkeypatch.setattr(
        sys, "argv",
        ["calibrate_terminal_ir.py", "--robot", "robot-01", "--input", str(dummy_input)]
    )
    with pytest.raises(SystemExit) as exc:
        cal.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "Terminal IR calibration requires --dock-id 1 through 5" in captured.err

    # Missing --dock-id with live capture args
    monkeypatch.setattr(
        sys, "argv",
        ["calibrate_terminal_ir.py", "--robot", "robot-01", "--label", "left", "--out", str(tmp_path / "out.jsonl")]
    )
    with pytest.raises(SystemExit) as exc:
        cal.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "Terminal IR calibration requires --dock-id 1 through 5" in captured.err


def test_cli_runs_input_analysis_with_dock_id(monkeypatch, tmp_path, capsys):
    trial_file = tmp_path / "trial.jsonl"
    trial_file.write_text(
        "\n".join(json.dumps(r) for r in position_records()) + "\n"
    )
    monkeypatch.setattr(
        sys, "argv",
        [
            "calibrate_terminal_ir.py",
            "--robot", "robot-01",
            "--dock-id", "4",
            "--input", str(trial_file),
        ]
    )
    cal.main()
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["robot_id"] == "robot-01"
    assert result["assigned_dock_id"] == 4
    assert result["dock_id_assigned"] is True
    assert result["candidate_differential_signal"] is True

def test_strict_terminal_ir_trial_reader_accepts_real_capture_shape(tmp_path):
    rows = position_records()
    path = tmp_path / "authentic_ir_trials.jsonl"
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    assert cal.load_trial_rows(path) == rows
    result = cal.analyze(cal.load_trial_rows(path), "robot-01", expected_dock_id=4)
    assert result["candidate_differential_signal"] is True
    assert result["motor_authorized"] is False
    assert result["physical_acceptance_pass"] is False


@pytest.mark.parametrize("original,early_field", [
    ('"label": "left"', '"label": "right"'),
    ('"received_monotonic": 1000.0', '"received_monotonic": 999.0'),
    ('"left_seq": 1', '"left_seq": 0'),
    ('"robot_id": "robot-01"', '"robot_id": "robot-02"'),
    ('"code": 0', '"code": 1234'),
])
def test_terminal_ir_trial_jsonl_cannot_override_recorded_evidence(
    tmp_path, original, early_field,
):
    row = position_records()[0]
    line = json.dumps(row)
    assert line.count(original) == 1
    path = tmp_path / "ambiguous_ir_trials.jsonl"
    path.write_text(line.replace(original, early_field + ", " + original) + "\n")
    with pytest.raises(ValueError, match="Duplicate terminal IR trial JSON field"):
        cal.load_trial_rows(path)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_terminal_ir_trial_jsonl_rejects_nonstandard_numeric_tokens(
    tmp_path, constant,
):
    line = json.dumps(position_records()[0])
    path = tmp_path / "nonfinite_ir_trials.jsonl"
    path.write_text(line.replace(
        '"received_monotonic": 1000.0',
        f'"received_monotonic": {constant}',
    ) + "\n")
    with pytest.raises(ValueError, match="Nonfinite terminal IR trial JSON constant"):
        cal.load_trial_rows(path)


def test_terminal_ir_evidence_append_is_private_and_keeps_all_positions(tmp_path):
    path = tmp_path / "private" / "dock_ir.jsonl"
    rows = position_records()
    for section in (rows[:20], rows[20:40], rows[40:]):
        cal.append_trial_rows(path, section)
    assert cal.load_trial_rows(path) == rows
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_terminal_ir_evidence_symlink_cannot_overwrite_other_file(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    original = tmp_path / "other.jsonl"
    original.write_text("DO NOT TOUCH", encoding="utf-8")
    link = directory / "trial.jsonl"
    link.symlink_to(original)
    with pytest.raises(OSError):
        cal.append_trial_rows(link, position_records()[:1])
    assert original.read_text(encoding="utf-8") == "DO NOT TOUCH"


def test_terminal_ir_evidence_rejects_parent_alias_without_side_effects(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe"):
        cal.append_trial_rows(alias / "trial.jsonl", position_records()[:1])
    assert not (actual / "trial.jsonl").exists()
    with pytest.raises(ValueError, match="Unsafe"):
        cal.append_trial_rows(
            tmp_path / "fresh" / ".." / "actual" / "injected.jsonl",
            position_records()[:1],
        )
    assert not (actual / "injected.jsonl").exists()


def test_terminal_ir_evidence_rejects_public_or_linked_file(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    public = directory / "public.jsonl"
    public.write_text("ORIGINAL", encoding="utf-8")
    os.chmod(public, 0o644)
    with pytest.raises(ValueError, match="owned private regular file"):
        cal.append_trial_rows(public, position_records()[:1])
    assert public.read_text(encoding="utf-8") == "ORIGINAL"
    os.chmod(public, 0o600)
    second_name = directory / "second.jsonl"
    os.link(public, second_name)
    with pytest.raises(ValueError, match="owned private regular file"):
        cal.append_trial_rows(second_name, position_records()[:1])
    assert public.read_text(encoding="utf-8") == "ORIGINAL"


def test_terminal_ir_evidence_rejects_nonregular_fifo_without_blocking(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    fifo = directory / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(OSError):
        cal.append_trial_rows(fifo, position_records()[:1])


@pytest.mark.parametrize(("origin", "robot_id"), [
    ("http://example.com:8765", "robot-01"),
    ("http://192.168.1.100:8765", "robot-01"),
    ("http://localhost:8765/other", "robot-01"),
    ("http://user:pass@localhost:8765", "robot-01"),
    ("http://localhost:8765?redirect=1", "robot-01"),
    ("http://localhost:8765#fragment", "robot-01"),
    ("ftp://localhost:8765", "robot-01"),
    ("http://localhost:99999", "robot-01"),
    ("http://localhost:8765\nInjected: yes", "robot-01"),
    ("http://localhost:8765", "robot-01/other"),
    ("http://localhost:8765", "robot-01?x=1"),
    ("http://localhost:8765", "x" * 41),
])
async def test_ir_capture_rejects_untrusted_token_origin_before_http(
    monkeypatch, origin, robot_id,
):
    def unexpected_client(*args, **kwargs):
        pytest.fail("Unsafe origin attempted to create an authenticated HTTP client")

    monkeypatch.setattr(cal.httpx, "AsyncClient", unexpected_client)
    with pytest.raises(ValueError):
        await cal.capture(origin, "T" * 32, robot_id, "left", 20, .05)


@pytest.mark.parametrize(("origin", "expected"), [
    ("http://127.0.0.1:8765", "http://127.0.0.1:8765"),
    ("http://localhost:8765/", "http://localhost:8765"),
    ("http://[::1]:8765", "http://[::1]:8765"),
    ("https://robot.example.com", "https://robot.example.com"),
])
def test_ir_capture_allows_loopback_http_or_remote_https(origin, expected):
    assert cal._safe_ir_origin(origin, "robot-01") == expected

