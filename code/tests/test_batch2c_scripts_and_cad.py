"""Batch 2C regression tests for scripts and CAD verification contracts."""
from __future__ import annotations

import json
import runpy
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "code/scripts"


def _load(name: str) -> dict:
    path_str = str(SCRIPTS)
    added = path_str not in sys.path
    if added:
        sys.path.insert(0, path_str)
    try:
        return runpy.run_path(str(SCRIPTS / name))
    finally:
        if added and path_str in sys.path:
            sys.path.remove(path_str)


def test_emit_wiring_manifest_detects_tof_bus_header_drift():
    """868gBxP: firmware TofBus.h address constants must match wiring plan."""
    mod = _load("emit_wiring_manifest.py")
    plan = json.loads((ROOT / mod["PLAN"]).read_text(encoding="utf-8"))
    body = (ROOT / mod["BODY_PINS"]).read_text(encoding="utf-8")
    head = (ROOT / mod["HEAD_PINS"]).read_text(encoding="utf-8")
    tof_h = (ROOT / mod["TOF_BUS_HEADER"]).read_text(encoding="utf-8")
    mod["verify"](plan, body, head, tof_header=tof_h)
    for orig, mutated in (
        ("kMuxAddress = 0x70;", "kMuxAddress = 0x72;"),
        ("kOptionalMuxAddress = 0x71;", "kOptionalMuxAddress = 0x73;"),
        ("kSensorAddress = 0x29;", "kSensorAddress = 0x30;"),
    ):
        with pytest.raises(ValueError):
            mod["verify"](plan, body, head, tof_header=tof_h.replace(orig, mutated, 1))


def test_verify_procurement_haptic_gate_rejects_unrelated_measurement():
    """868YPlc: haptic thermal gate rejects unrelated non-haptic measurements."""
    mod = _load("verify_procurement_receipts.py")
    unrelated = {
        "sample_count": 6,
        "conditions": {"setup": "bench", "instrument": "scale"},
        "quantities": [{"name": "shipping_weight", "unit": "g", "value": 100}],
    }
    assert mod["_qualified_gate_measurement"](
        "haptic_hc123_one_shot_stuck_i2c_and_motor_thermal_trial", unrelated,
    ) is False
    valid = {
        "sample_count": 6,
        "conditions": {
            "setup": "HC123 + AO3400 coin motor bench",
            "instrument": "Rigol scope + K-type thermocouple",
            "installed_hardware": "haptic-rev1",
            "procedure_revision": "proc-1",
            "hc123_circuit_revision": "hc123-rev1",
            "oscilloscope_capture_id": "scope-01",
            "current_capture_id": "curr-01",
            "thermal_capture_id": "therm-01",
        },
        "quantities": [
            {"name": "normal_operation_trials", "unit": "trials",
             "value": 3, "minimum": 3, "maximum": 3},
            {"name": "stuck_i2c_fault_trials", "unit": "trials",
             "value": 3, "minimum": 3, "maximum": 3},
            {"name": "minimum_pulse_spacing_s", "unit": "s",
             "value": 1.6, "minimum": 1.5, "maximum": 2.0},
            {"name": "measured_pulse_duration_ms", "unit": "ms",
             "value": 80.0, "minimum": 75.0, "maximum": 85.0},
            {"name": "measured_motor_current_ma", "unit": "mA",
             "value": 90.0, "minimum": 80.0, "maximum": 100.0},
            {"name": "measured_motor_temperature_c", "unit": "C",
             "value": 42.0, "minimum": 25.0, "maximum": 45.0},
            {"name": "unbounded_continuous_energizations", "unit": "events",
             "value": 0, "minimum": 0, "maximum": 0},
        ],
    }
    assert mod["_qualified_gate_measurement"](
        "haptic_hc123_one_shot_stuck_i2c_and_motor_thermal_trial", valid,
    ) is True


def test_calibrate_terminal_ir_requires_per_receiver_ids_in_inferred_mode():
    """868cBWs: inferred dock mode still requires both left_code and right_code."""
    mod = _load("calibrate_terminal_ir.py")
    row = {
        "robot_id": "robot-01",
        "left_valid": True, "right_valid": True, "match": True,
        "left_seq": 1, "right_seq": 1, "left_age_ms": 20, "right_age_ms": 20,
        "code": 0xCB34ED12,
        "motor_authorized": False, "charging_authorized": False,
        "physical_qualified": False,
    }
    with pytest.raises(ValueError, match="receiver identities"):
        mod["_validate_trial_ir"](row, "robot-01", None)
    identified = {**row, "left_code": 0xCB34ED12, "right_code": 0xCB34ED12}
    assert mod["_validate_trial_ir"](identified, "robot-01", None)["code"] == 0xCB34ED12


def test_export_fit_kit_rejects_concurrent_scad_edit_during_footprint(tmp_path, monkeypatch):
    """868cabS: SCAD edit during footprint check prevents publishing fit_kit_manifest.json."""
    import importlib.util
    import shutil
    from struct import pack

    spec = importlib.util.spec_from_file_location("export_fit_b2c", SCRIPTS / "export_fit_kit.py")
    efk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(efk)
    scad_dir = tmp_path / "docs/cad/remixes"
    (scad_dir / "dock").mkdir(parents=True)
    for rel in (
        "one_robot_adapter_kit.scad", "remaining_fit_gauges.scad",
        "speaker_rect_fit_gauge.scad", "mg90s_pocket_fit_gauges.scad",
        "vl53l0x_gy530_fit_gauge.scad", "dock/dock_passive_fit.scad",
    ):
        shutil.copy2(ROOT / "docs/cad/remixes" / rel, scad_dir / rel)
    out = tmp_path / "out"
    calls = {"fp": 0}

    def _cube_binstl() -> bytes:
        c = (
            (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0),
            (0.0, 0.0, 10.0), (10.0, 0.0, 10.0), (10.0, 10.0, 10.0), (0.0, 10.0, 10.0),
        )
        tris = [
            (0, 3, 2), (0, 2, 1), (4, 5, 6), (4, 6, 7),
            (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
            (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
        ]
        buf = bytearray(b"cube".ljust(80, b"\0") + pack("<I", len(tris)))
        for i0, i1, i2 in tris:
            buf.extend(pack("<12fH", 0.0, 0.0, 0.0, *c[i0], *c[i1], *c[i2], 0))
        return bytes(buf)

    def fake_run(cmd, **_kwargs):
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_bytes(_cube_binstl())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_footprint(_root, _out):
        calls["fp"] += 1
        target = scad_dir / "one_robot_adapter_kit.scad"
        target.write_text(target.read_text(encoding="utf-8") + "\n// mutated\n", encoding="utf-8")
        return {"ok": True}

    monkeypatch.setattr(efk.shutil, "which", lambda _cmd: "/fake/openscad")
    monkeypatch.setattr(efk.subprocess, "run", fake_run)
    monkeypatch.setattr(efk, "ADAPTERS", ("tof_adjustable",))
    monkeypatch.setattr(efk, "GAUGES", ())
    monkeypatch.setattr(efk, "SPEAKER_FITS", ())
    monkeypatch.setattr(efk, "MG90S_FITS", ())
    monkeypatch.setattr(efk, "RANGER_FITS", ())
    monkeypatch.setattr(efk, "DOCKS", ())
    monkeypatch.setattr(efk, "reference_body_footprint_screen", fake_footprint)
    with pytest.raises(ValueError, match="SCAD source changed during export"):
        efk.export_kit(tmp_path, output_dir=out)
    assert calls["fp"] == 1
    assert not (out / "fit_kit_manifest.json").exists()


def test_i2c_electrical_preflight_rejects_mixed_3v3_and_5v_pullup():
    """868eplv: mixed 3.3V and 5V pullups on the same lane must fail closed."""
    mod = _load("i2c_electrical_preflight.py")
    screen = mod["screen_selected_segment"]
    upstream = {
        "sda": {"pullup_v": 3.3, "pullup_ohms": [10000], "cap_pf": 30},
        "scl": {"pullup_v": 3.3, "pullup_ohms": [10000], "cap_pf": 30},
    }
    selected_mixed = {
        "sda": {
            "pullup_v": 3.3,
            "pullup_ohms": [10000, 10000],
            "pullup_rails_v": [3.3, 5.0],
            "cap_pf": 40,
        },
        "scl": {
            "pullup_v": 3.3,
            "pullup_ohms": [10000, 10000],
            "pullup_rails_v": [3.3, 3.3],
            "cap_pf": 40,
        },
    }
    with pytest.raises(ValueError, match="not 3.3V"):
        screen(upstream, selected_mixed)
    selected_ok = {
        "sda": {
            "pullup_ohms": [{"ohms": 10000, "pullup_v": 3.3}, {"ohms": 10000, "pullup_v": 3.3}],
            "cap_pf": 40,
        },
        "scl": {
            "pullup_ohms": [{"ohms": 10000, "pullup_v": 3.3}, {"ohms": 10000, "pullup_v": 3.3}],
            "cap_pf": 40,
        },
    }
    assert screen(upstream, selected_ok)["selected_branch_paper_pass"] is True


def test_power_preflight_sizes_integrated_stack_from_screened_converter_min():
    """868f6eq: integrated stack uses 2.9V dropout-screened converter input minimum."""
    mod = _load("power_preflight.py")
    stack = mod["screen_one_cell_power_stack"](
        active_peak_5v_a=1.6, active_sustained_5v_a=0.4,
        dock_idle_5v_a=0.2, charge_request_a=0.4,
        charger_variant="BQ24075",
        pack_mm=(50, 30, 10), tray_mm=(68, 35, 14),
        pack_peak_a=10, pack_sustained_a=8, pcm_trip_a=12,
        connector_a=8, wire_crimp_a=8,
        boost_input_max_a=12, boost_input_continuous_a=10,
        boost_output_at_3v_continuous_a=3,
        boost_regulator_min_input_v=2.8, boost_regulator_max_input_v=22,
        regulator_topology="buck_boost",
        charger_input_limit_a=1.4, charger_thermal_input_a=1.4,
        dock_adapter_continuous_a=2.0, pack_charge_max_a=1.0,
        docked_sys_v=5.5,
        charge_temperature_sensor_connected=True,
        charger_ts_fixed_resistor_removed=True, dock_motors_disarmed=True,
        guaranteed_charge_window_c=(0, 45),
        ts_open_inhibit_on_paper=True, ts_short_inhibit_on_paper=True,
        pack_path_fuse_derated_hold_a=8,
        pack_shunt_milliohm=5, pack_shunt_rated_w=2, pack_shunt_derated_w=1,
        charger_pgood_routed_on_paper=True,
    )
    # At 3.0 V: (5 * 1.6 * 1.3) / (3.0 * 0.85) = 4.079 A (<= 4.5 A)
    # At 2.9 V: (5 * 1.6 * 1.3) / (2.9 * 0.85) = 4.220 A (> 4.079 A)
    assert stack["minimum_1s_peak_a_including_margin"] > 4.2


def test_estimate_clock_drift_4s_reports_short_capture_uncertainty_bound():
    """868LaWR: 4-second synthetic capture explicitly flags >25 ppm resolution bound."""
    mod = _load("estimate_aec_delay.py")
    rng = np.random.default_rng(7)
    ref = np.convolve(rng.normal(0, 0.15, 64000), np.ones(8) / 8, mode="same")
    pos = np.arange(len(ref))
    mic = np.interp(pos - 1120 - pos * 200 / 1_000_000, pos, ref, left=0, right=0)
    report = mod["estimate_clock_drift"](ref, mic)
    assert report["clock_drift_within_25ppm_bound"] is False
    assert report["clock_drift_uncertainty_ppm"] > 25.0
    assert report["clock_drift_needs_hardware_review"] is True


def test_calibrate_dock_camera_rejects_near_frontal_views_even_when_spread():
    """868RjLb: reject near-frontal checkerboard poses with low angular tilt."""
    mod = _load("calibrate_dock_camera.py")
    import cv2

    w, h = 640, 480
    cam = np.array([[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]])
    dist = np.zeros(5)
    grid = np.zeros((6 * 9, 3), np.float32)
    grid[:, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2) * 10.0
    # 12 near-frontal views (max ~3.4 deg tilt) with wide X/Y/Z spread (> 8 px separation).
    views = []
    for idx in range(12):
        rx = 0.03 * ((idx % 3) - 1)
        ry = 0.03 * (((idx // 3) % 3) - 1)
        dx = -90 + 45 * (idx % 4)
        dy = -70 + 45 * (idx // 4)
        dz = 300 + 25 * (idx % 4)
        pts, _ = cv2.projectPoints(
            grid, np.array([[rx], [ry], [0.0]]),
            np.array([[float(dx)], [float(dy)], [float(dz)]]), cam, dist,
        )
        views.append(pts)
    with pytest.raises(ValueError, match="too nearly frontal"):
        mod["fit_corners"](
            views, (w, h), columns=9, rows=6, square_mm=10.0,
            tag_side_mm=25.0, marker_id=1, target_distance_mm=120.0,
        )


@pytest.mark.parametrize(
    "status,valid",
    [
        (None, False),
        ("unavailable", False),
        ("backordered", False),
        ("unknown", False),
        ("orderable", True),
        ("in_stock", True),
    ],
)
def test_landed_cost_requires_affirmative_stock_availability_for_release(
    status, valid,
):
    """868o66K: strict release scopes require orderable/in_stock receipt."""
    mod = _load("landed_cost.py")
    today = date.today().isoformat()
    line = {
        "role_key": "robot:pack",
        "seller": "A",
        "sku": "p1",
        "quantity_packages": 1,
        "units_per_package": 1,
        "package_price_usd": "10.00",
        "quote_reference": "q1",
        "quoted_at": today,
        "stock_checked_at": today,
        "stock_evidence_url": "https://supplier.example/p1",
    }
    if status is not None:
        line["stock_availability"] = status
    ev = {
        "scope": "first_robot",
        "currency": "USD",
        "paid_orders_complete": True,
        "lines": [line],
        "seller_charges": [{
            "seller": "A", "shipping_usd": "0.00",
            "tax_usd": "0.00", "duties_usd": "0.00", "discount_usd": "0.00",
        }],
        "inventory": [],
        "paid_in_flight": [],
        "paid_orders": [],
    }
    res = mod["account_landed_cost"](ev, {"robot:pack": 1}, {"robot:pack": "robot"})
    assert (not res["errors"]) is valid


def test_barge_in_tracks_actuator_noise_subgate_and_false_vad_starts(tmp_path):
    """868mcaO: missing actuator-load record keeps subgate open; false VAD fails."""
    sys.path.insert(0, str(ROOT / "code/tests"))
    try:
        from test_barge_in_trials import both_distances
    finally:
        sys.path.pop(0)
    mod = _load("check_barge_in_trials.py")
    rows = both_distances()
    rep = mod["evaluate"](rows)
    assert rep["meets_actuator_noise_subgate"] is False
    assert "open" in rep["robot_only_actuator_subgate_status"]
    rows_with_act = [dict(r) for r in rows]
    rows_with_act[-2]["actuator_load_during_tts_observed"] = True
    rows_with_act[-2]["false_vad_starts"] = 0
    rows_with_act.append({
        "kind": "actuator_only", "duration_seconds": 60,
        "actuator_load_observed": True, "false_vad_starts": 0,
    })
    rep_ok = mod["evaluate"](rows_with_act)
    assert rep_ok["meets_actuator_noise_subgate"] is True


def test_serial_bench_preserves_halt_failure_and_structured_receipt(monkeypatch, capsys):
    """868qcWN: structured receipt emitted on halt and failed halt surfaces clearly."""
    class FakePort:
        def __init__(self, responses):
            self.responses = list(responses)
            self.in_waiting = 0

        def write(self, data):
            return len(data)

        def reset_input_buffer(self):
            pass

        def flush(self):
            pass

        def read_until(self, _sep, size=1920):
            return self.responses.pop(0)

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setitem(
        sys.modules,
        "serial",
        SimpleNamespace(Serial=lambda *a, **kw: FakePort([b"OK halt\n"])),
    )
    import importlib.util
    spec = importlib.util.spec_from_file_location("serial_bench_b2c", SCRIPTS / "serial_bench.py")
    sb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sb)
    monkeypatch.setattr(sb, "require_local_serial_device", lambda _p: None)
    monkeypatch.setattr(sb.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        sys, "argv", ["serial_bench.py", "--port", "/dev/cu.usbserial-1", "--command", "halt"],
    )
    sb.main()
    out = json.loads(capsys.readouterr().out)
    assert out["acknowledged"] is True
    assert out["physical_stop_verified"] is False
    assert out["receipt"]["matched_response_bytes"] == 8

    # Primary command error must not be hidden when finally halt also fails.
    class FailingHaltPort(FakePort):
        def read_until(self, _sep, size=1920):
            if not self.responses:
                raise RuntimeError("Halt lost")
            return self.responses.pop(0)

    monkeypatch.setattr(sb, "inspect_status", lambda _s: {
        "eligible_for_manual_local_rearm": True,
        "armed": False, "local_guard_ready": True, "local_guard_fault": None,
    })
    monkeypatch.setattr(
        sb,
        "serial",
        SimpleNamespace(Serial=lambda *a, **kw: FailingHaltPort([
            b'{"ok":true}\n', b"OK rearm\n", b"OK arm\n", b"ERR motion_blocked\n",
        ])),
    )
    monkeypatch.setattr(
        sys, "argv",
        ["serial_bench.py", "--port", "/dev/cu.usbserial-1",
         "--command", "grip 95", "--local-rearm"],
    )
    with pytest.raises(RuntimeError, match="ERR motion_blocked") as exc_info:
        sb.main()
    assert any("Final halt failed" in note for note in getattr(exc_info.value, "__notes__", []))
