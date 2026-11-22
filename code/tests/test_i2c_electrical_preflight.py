"""Electrical lane and pullup laws, source matched to actual WROOM topology."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "scripts/i2c_electrical_preflight.py"
spec = importlib.util.spec_from_file_location("i2c_electrical_preflight", SRC)
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def segment(upstream_pullups=(4700, 4700), downstream_pullups=(4700,),
            cap_up_pf=40, cap_down_pf=80, pullup_v=3.3):
    return ({
        k: {"pullup_v": 3.3, "pullup_ohms": list(upstream_pullups),
            "cap_pf": cap_up_pf}
        for k in ("sda", "scl")
    }, {
        k: {"pullup_v": pullup_v,
            "pullup_ohms": list(downstream_pullups), "cap_pf": cap_down_pf}
        for k in ("sda", "scl")
    })


def test_all_sixteen_visited_and_no_unverified_lane_is_a_purchase_pass():
    report = tool.audit()
    assert report["device_source_lanes"] == 16
    assert report["all_16_lanes_evaluated"]
    assert not report["all_16_lanes_paper_pass"]
    assert not report["all_16_lanes_physically_qualified"]
    assert not report["entire_five_robot_order_electrically_approved"]
    assert [x["branch"] for x in report["lanes"]] == [
        f"0x{mux:02X}:{channel}" for mux in (0x70, 0x71)
        for channel in range(8)]
    assert all(x["status"] == "HOLD_MISSING_ELECTRICAL_VALUES"
               for x in report["lanes"])


def test_each_source_lane_proves_no_i2c_address_conflict_within_one_channel():
    lanes = tool.topology()
    assert all(len({d["address"] for d in lane["devices"]})
               == len(lane["devices"]) for lane in lanes)
    assert [d["address"] for d in lanes[0]["devices"]] == [0x29]
    # Duplicate AS5600 0x36 devices across isolated branches ARE allowed.
    assert [lanes[9]["devices"][1]["address"],
            lanes[12]["devices"][1]["address"],
            lanes[14]["devices"][0]["address"],
            lanes[15]["devices"][0]["address"]] == [0x36] * 4
    assert {0x36} <= {d["address"] for lane in lanes
                      for d in lane["devices"]}


def test_three_4k7_pullups_across_live_bus_have_valid_fast_mode_window():
    upstream, downstream = segment()
    report = tool.screen_selected_segment(upstream, downstream)
    assert report["selected_branch_paper_pass"]
    assert report["lines"]["sda"]["combined_ohms"] == pytest.approx(1566.667, abs=.001)
    assert report["lines"]["sda"]["estimated_rise_ns"] == pytest.approx(159.2924, abs=.01)
    assert report["lines"]["sda"]["estimated_sink_ma"] == pytest.approx(1.851, abs=.01)
    assert not report["qualified_hardware"]


def test_parallel_banked_breakout_pullups_cause_excess_sink_current():
    upstream, downstream = segment(upstream_pullups=(4700, 4700, 4700, 4700),
                                   downstream_pullups=(4700,))
    report = tool.screen_selected_segment(upstream, downstream)
    assert report["lines"]["sda"]["combined_ohms"] == pytest.approx(940)
    assert report["lines"]["sda"]["estimated_sink_ma"] > 3
    assert not report["selected_branch_paper_pass"]


def test_four_k_seven_single_pullup_can_be_too_weak_for_400khz_rise():
    upstream, downstream = segment(upstream_pullups=(4700,),
                                   downstream_pullups=(), cap_down_pf=80)
    assert not tool.screen_selected_segment(upstream, downstream)[
        "selected_branch_paper_pass"]


def test_high_capacitance_fails_fast_mode_even_with_reasonable_resistors():
    upstream, downstream = segment(cap_up_pf=70, cap_down_pf=230)
    report = tool.screen_selected_segment(upstream, downstream)
    assert report["lines"]["sda"]["estimated_rise_ns"] > 300
    assert not report["selected_branch_paper_pass"]


def test_one_carrier_pulled_up_to_5v_fails_not_translated_by_assumption():
    upstream, downstream = segment(pullup_v=5.0)
    with pytest.raises(ValueError, match="not 3.3V"):
        tool.screen_selected_segment(upstream, downstream)


def test_measured_unsafe_rise_and_voltage_low_override_paper_rc_pass():
    upstream, downstream = segment()
    downstream["sda"]["measured_rise_ns"] = 540
    assert not tool.screen_selected_segment(upstream, downstream)[
        "selected_branch_paper_pass"]
    downstream["sda"]["measured_rise_ns"] = 180
    downstream["sda"]["measured_low_v"] = 0.45
    assert not tool.screen_selected_segment(upstream, downstream)[
        "selected_branch_paper_pass"]


@pytest.mark.parametrize("value", [True, "4700", 0, -1, float("nan"),
                                   float("inf"), 10**1000])
def test_invalid_pullup_and_capacitance_inputs_rejected(value):
    upstream, downstream = segment()
    downstream["sda"]["pullup_ohms"] = [value]
    with pytest.raises(ValueError):
        tool.screen_selected_segment(upstream, downstream)
    upstream, downstream = segment()
    downstream["sda"]["cap_pf"] = value
    with pytest.raises(ValueError):
        tool.screen_selected_segment(upstream, downstream)


@pytest.mark.parametrize("ohms", [1e-320, 1e308])
def test_pathological_parallel_resistors_fail_closed_without_division_crashes(ohms):
    upstream, downstream = segment()
    downstream["sda"]["pullup_ohms"] = [ohms]
    if ohms < 1:
        with pytest.raises(ValueError, match="pullup network"):
            tool.screen_selected_segment(upstream, downstream)
    else:
        report = tool.screen_selected_segment(upstream, downstream)
        assert report["selected_branch_paper_pass"]
        assert report["lines"]["sda"]["installed_pullups"] == 3


@pytest.mark.parametrize("reading", [True, "0.3", -0.1, float("nan"),
                                     float("inf"), 10**1000])
def test_malformed_measured_low_level_cannot_crash_safety_review(reading):
    upstream, downstream = segment()
    downstream["scl"]["measured_low_v"] = reading
    with pytest.raises(ValueError, match="measured_low_v invalid"):
        tool.screen_selected_segment(upstream, downstream)


def test_lane_mutations_fail_before_part_selection():
    import json
    plan = json.loads(tool.PLAN.read_text())
    bad = copy.deepcopy(plan)
    bad["bus"]["mux_extras"]["channels"][1]["devices"][1]["address"] = 0x39
    with pytest.raises(ValueError, match="Address conflict"):
        tool.topology(bad)
    bad = copy.deepcopy(plan)
    bad["bus"]["mux_extras"]["address"] = 0x70
    with pytest.raises(ValueError, match="Incorrect mux address"):
        tool.topology(bad)
    bad = copy.deepcopy(plan)
    bad["bus"]["mux_extras"]["channels"].pop()
    with pytest.raises(ValueError, match="All eight lanes"):
        tool.topology(bad)
    bad = copy.deepcopy(plan)
    bad["range_breakout_power_contract"]["module_vin_v"] = 5.0
    with pytest.raises(ValueError, match="3.3V sensor bus"):
        tool.topology(bad)


def test_both_muxes_need_every_lane_qualified_even_if_15_pass():
    up, down = segment()
    upstream = {"sda": up["sda"], "scl": up["scl"]}
    branches = {
        f"0x{mux:02X}:{n}": down for mux in (0x70, 0x71)
        for n in range(8)
    }
    completed = tool.audit({"upstream": upstream, "branches": branches})
    assert completed["all_16_lanes_paper_pass"]
    assert not completed["entire_five_robot_order_electrically_approved"]
    del branches["0x71:7"]
    incomplete = tool.audit({"upstream": upstream, "branches": branches})
    assert not incomplete["all_16_lanes_paper_pass"]
    assert incomplete["lanes"][-1]["status"] == "HOLD_MISSING_ELECTRICAL_VALUES"


@pytest.mark.parametrize("body", [
    '{"upstream":{"sda":{"pullup_v":5.0,"pullup_v":3.3}},"branches":{}}',
    '{"upstream":{},"branches":{"0x70:0":{},"0x70:0":{}}}',
    '{"upstream":{},"branches":{},"upstream":{}}',
])
def test_cli_rejects_ambiguous_electrical_measurement(tmp_path, body):
    evidence = tmp_path / "contradictory-i2c.json"
    evidence.write_text(body, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SRC), "--evidence", str(evidence)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Duplicate I2C electrical evidence key" in result.stderr
    assert '"all_16_lanes_paper_pass": true' not in result.stdout


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_cli_rejects_nonfinite_electrical_json_constants(tmp_path, constant):
    evidence = tmp_path / "nonfinite-i2c.json"
    evidence.write_text(
        '{"upstream":{},"branches":{},"spurious":' + constant + '}',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SRC), "--evidence", str(evidence)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Nonfinite I2C electrical evidence constant" in result.stderr


def test_cli_valid_unqualified_electrical_json_remains_on_hold(tmp_path):
    evidence = tmp_path / "unqualified-i2c.json"
    evidence.write_text('{"upstream":{},"branches":{}}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SRC), "--evidence", str(evidence)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["all_16_lanes_evaluated"]
    assert not report["all_16_lanes_paper_pass"]
    assert not report["all_16_lanes_physically_qualified"]
