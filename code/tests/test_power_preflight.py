"""Electrical arithmetic only, never substitutes for measuring hardware."""
import runpy
from pathlib import Path

import pytest

tool = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
))["size_5v_supply"]

docked = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
))["assess_docked_load"]


def test_real_docked_load_formula_accepts_correct_bq24075_sys_voltage_only():
    """BQ24075 5.5V output is not automatically an overvoltage measurement."""
    assess = runpy.run_path(str(
        Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    ))["assess_docked_load"]
    base = dict(measured_sys_v=5.5, measured_boost_efficiency=0.85,
                motors_confirmed_disarmed=True)
    with pytest.raises(ValueError):
        assess(0.3, 0.2, **base)  # no guessed docked SYS envelope
    report = assess(0.3, 0.2, charger_variant="BQ24075", **base)
    assert report["charger_variant"] == "BQ24075"
    assert report["charger_variant_max_docked_out_v"] == 5.6
    assert report["fixed_5v_rail_requires_separate_converter"]
    assert report["candidate_docked_load_on_paper"] is None
    assert report["candidate_physically_qualified"] is False
    with pytest.raises(ValueError):
        assess(0.3, 0.2, charger_variant="BQ24073", **base)
    with pytest.raises(ValueError):
        assess(0.3, 0.2, charger_variant="BQ24075",
               measured_sys_v=5.7, measured_boost_efficiency=0.85)


def test_bq24074_and_bq24075_are_not_interchangeable_five_volt_rails():
    """Read the actual TI Rev N output voltage rows, not the IC family label."""
    screen = runpy.run_path(str(
        Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    ))["screen_bq2407x_output_path"]
    dock75 = screen("BQ24075", regulator_min_input_v=2.8,
                    regulator_max_input_v=5.0)
    assert dock75["docked_output_max_v"] == 5.6
    assert not dock75["regulator_covers_charger_output_on_paper"]
    # Wide VIN is not enough: a boost-only converter cannot reduce a
    # possible BQ24075 5.6 V SYS node to the required regulated 5 V.
    wrong_topology = screen("BQ24075", regulator_min_input_v=2.8,
                            regulator_max_input_v=22.0)
    assert not wrong_topology["topology_supports_regulating_5v_both_modes"]
    assert not wrong_topology["regulator_covers_charger_output_on_paper"]
    enough = screen("BQ24075", regulator_min_input_v=2.8,
                    regulator_max_input_v=22.0,
                    regulator_topology="buck_boost")
    assert enough["regulator_covers_charger_output_on_paper"]
    assert enough["topology_supports_regulating_5v_both_modes"]
    assert not enough["charger_and_5v_rail_physically_qualified"]
    assert not enough["real_docked_voltage_measured"]
    assert not screen("BQ24075", regulator_min_input_v=2.8,
                      regulator_max_input_v=22.0,
                      bypasses_5v_regulator=True)[
                      "regulator_covers_charger_output_on_paper"]
    dock74 = screen("BQ24074", regulator_min_input_v=2.8,
                    regulator_max_input_v=5.0)
    assert dock74["docked_output_max_v"] == 4.5
    assert dock74["regulator_covers_charger_output_on_paper"]
    with pytest.raises(ValueError):
        screen("BQ24073", regulator_min_input_v=2.8,
               regulator_max_input_v=22.0)
    with pytest.raises(ValueError):
        screen("BQ24075", regulator_min_input_v=True,
               regulator_max_input_v=22.0)
    with pytest.raises(ValueError, match="topology"):
        screen("BQ24075", regulator_min_input_v=2.8,
               regulator_max_input_v=22.0, regulator_topology="buck_only")
    with pytest.raises(ValueError, match="topology"):
        screen("BQ24075", regulator_min_input_v=2.8,
               regulator_max_input_v=22.0, regulator_topology=True)



def test_full_one_pet_load_derates_low_single_cell_voltage():
    report = tool(3, 1.8)
    assert report["minimum_rated_5v_output_a"] == 3.9
    assert report["minimum_rated_cell_and_boost_input_a"] > 7.6
    assert not report["physical_load_verified"]
    assert not report["charger_and_load_sharing_verified"]
    assert not report["candidate_physically_qualified"]


def test_boost_five_amp_is_input_current_not_guaranteed_output():
    bad = tool(
        3, 1.8, boost_max_input_a=5, boost_continuous_input_a=5,
        boost_continuous_output_a=5, protected_cell_continuous_a=10,
    )
    assert bad["candidate_electrically_sufficient_on_paper"] is False
    generous = tool(
        1, .6, boost_max_input_a=5, boost_continuous_input_a=5,
        boost_continuous_output_a=3, protected_cell_continuous_a=5,
    )
    assert generous["candidate_electrically_sufficient_on_paper"] is True
    assert generous["candidate_physically_qualified"] is False


@pytest.mark.parametrize("peak,average", [(0, 1), (1, 2), (-1, 1), (float("nan"), 1)])
def test_power_sizing_rejects_absent_and_bad_loads(peak, average):
    with pytest.raises(ValueError):
        tool(peak, average)


def test_candidate_never_approved_by_rounding_down_current_requirement():
    # Actual input need is 1.529411... A, so the displayed minimum is
    # conservatively rounded UP to 1.530 rather than a misleading 1.529.
    low = tool(
        0.6, 0.4, boost_max_input_a=1.529, boost_continuous_input_a=1.529,
        boost_continuous_output_a=1, protected_cell_continuous_a=2,
    )
    assert low["minimum_rated_cell_and_boost_input_a"] == 1.53
    assert low["candidate_electrically_sufficient_on_paper"] is False
    enough = tool(
        0.6, 0.4, boost_max_input_a=1.53, boost_continuous_input_a=1.53,
        boost_continuous_output_a=1, protected_cell_continuous_a=2,
    )
    assert enough["candidate_electrically_sufficient_on_paper"] is True
    assert enough["candidate_physically_qualified"] is False


def test_exact_decimal_sizing_boundary_is_accepted_without_float_error():
    # 3 * 1.3 == 3.9 A exactly in stated decimal measurements.
    result = tool(
        3, 1.8, boost_max_input_a=8, boost_continuous_input_a=5,
        boost_continuous_output_a=3.9, protected_cell_continuous_a=8,
    )
    assert result["minimum_rated_5v_output_a"] == 3.9
    assert result["candidate_electrically_sufficient_on_paper"] is True


def test_continuous_cell_input_is_reported_separately_from_peak():
    report = tool(3, 1.8, cell_low_v=3.0, measured_boost_efficiency=0.85)
    assert report["minimum_continuous_cell_input_a"] == 4.589
    assert report["minimum_rated_cell_and_boost_input_a"] > report["minimum_continuous_cell_input_a"]
    assert report["thermal_and_brownout_verified"] is False


def test_missing_continuous_input_rating_cannot_qualify_candidate():
    report = tool(1, 0.6, boost_max_input_a=5,
                  boost_continuous_output_a=3, protected_cell_continuous_a=5)
    assert report["candidate_electrically_sufficient_on_paper"] is None
    assert report["candidate_physically_qualified"] is False


def test_sustained_input_thermal_limit_rejects_peak_capable_boost():
    insufficient = tool(3, 1.8, boost_max_input_a=9,
                        boost_continuous_input_a=4.5,
                        boost_continuous_output_a=4, protected_cell_continuous_a=9)
    assert insufficient["minimum_continuous_cell_input_a"] == 4.589
    assert insufficient["candidate_electrically_sufficient_on_paper"] is False
    sufficient_on_paper = tool(3, 1.8, boost_max_input_a=9,
                               boost_continuous_input_a=4.589,
                               boost_continuous_output_a=4, protected_cell_continuous_a=9)
    assert sufficient_on_paper["candidate_electrically_sufficient_on_paper"] is True
    assert sufficient_on_paper["candidate_physically_qualified"] is False


@pytest.mark.parametrize("rating", [0, -1, float("nan"), float("inf"), True])
def test_invalid_sustained_input_rating_is_rejected(rating):
    with pytest.raises(ValueError):
        tool(1, .6, boost_continuous_input_a=rating)


def test_sub_milliamp_rating_does_not_bypass_published_conservative_minimum():
    # 5 * 1.3 * 1.8 / (3 * .85) = 4.588235... A continuously.
    # The reported 4.589 A is the qualification threshold, not 4.5885 A.
    ratings = dict(boost_max_input_a=9, boost_continuous_output_a=4,
                   protected_cell_continuous_a=9)
    insufficient = tool(3, 1.8, boost_continuous_input_a=4.5885, **ratings)
    assert insufficient["minimum_continuous_cell_input_a"] == 4.589
    assert insufficient["candidate_electrically_sufficient_on_paper"] is False
    sufficient = tool(3, 1.8, boost_continuous_input_a=4.589, **ratings)
    assert sufficient["candidate_electrically_sufficient_on_paper"] is True
    assert sufficient["candidate_physically_qualified"] is False


def test_contradictory_boost_input_ratings_are_rejected():
    # A continuous board input rating cannot exceed its stated maximum.
    with pytest.raises(ValueError, match="Continuous boost input rating"):
        tool(1, 0.6, boost_max_input_a=3, boost_continuous_input_a=4,
             boost_continuous_output_a=3, protected_cell_continuous_a=5)
    # A coherent specification remains eligible for paper sizing only.
    report = tool(1, 0.6, boost_max_input_a=4, boost_continuous_input_a=3,
                  boost_continuous_output_a=3, protected_cell_continuous_a=5)
    assert report["candidate_electrically_sufficient_on_paper"] is True
    assert report["candidate_physically_qualified"] is False


@pytest.mark.parametrize("missing", [
    "boost_max_input_a",
    "boost_continuous_input_a",
    "boost_continuous_output_a",
    "protected_cell_continuous_a",
])
def test_each_missing_component_rating_blocks_paper_qualification(missing):
    # An incomplete published board/cell specification is not evidence of
    # simultaneous peak and continuous supply capability.
    ratings = dict(boost_max_input_a=9, boost_continuous_input_a=5,
                   boost_continuous_output_a=4, protected_cell_continuous_a=9)
    ratings.pop(missing)
    report = tool(3, 1.8, **ratings)
    assert report["candidate_electrically_sufficient_on_paper"] is None
    assert report["candidate_physically_qualified"] is False
    assert report["charger_and_load_sharing_verified"] is False


@pytest.mark.parametrize("field", [
    "cell_low_v", "measured_boost_efficiency", "margin",
    "boost_max_input_a", "boost_continuous_input_a",
    "boost_continuous_output_a", "protected_cell_continuous_a",
])
def test_boolean_values_never_masquerade_as_measured_power_or_ratings(field):
    # Python bool is a subclass of int. A JSON true must not become a
    # measured 1 A rating, 1 V threshold, or 100 percent efficiency.
    with pytest.raises(ValueError):
        tool(1, 0.6, **{field: True})


@pytest.mark.parametrize("peak,continuous", [(True, 0.6), (1, True)])
def test_boolean_load_telemetry_is_not_a_current_measurement(peak, continuous):
    with pytest.raises(ValueError):
        tool(peak, continuous)


def test_low_cell_voltage_and_efficiency_cannot_improve_input_current_requirement():
    # A converter's advertised 5V output rating alone cannot qualify a 1S
    # supply. Worse measured efficiency or a lower cell voltage increases the
    # required battery and converter input current for the same 5V load.
    nominal = tool(2, 1.2, cell_low_v=3.5, measured_boost_efficiency=0.9)
    low_cell = tool(2, 1.2, cell_low_v=3.0, measured_boost_efficiency=0.9)
    low_efficiency = tool(2, 1.2, cell_low_v=3.5, measured_boost_efficiency=0.7)
    for degraded in (low_cell, low_efficiency):
        assert degraded["minimum_rated_cell_and_boost_input_a"] > nominal["minimum_rated_cell_and_boost_input_a"]
        assert degraded["minimum_continuous_cell_input_a"] > nominal["minimum_continuous_cell_input_a"]
        assert degraded["candidate_physically_qualified"] is False
        assert degraded["charger_and_load_sharing_verified"] is False


@pytest.mark.parametrize("undersized,limit", [
    ("boost_max_input_a", 7.0),
    ("boost_continuous_input_a", 4.0),
    ("boost_continuous_output_a", 3.0),
    ("protected_cell_continuous_a", 7.0),
])
def test_each_independent_supply_rating_must_cover_simultaneous_load(undersized, limit):
    # A generous rating on the other three components must never mask a
    # bottleneck in the boost input, output or protected cell discharge path.
    ratings = dict(boost_max_input_a=9.0, boost_continuous_input_a=5.0,
                   boost_continuous_output_a=4.0, protected_cell_continuous_a=9.0)
    ratings[undersized] = limit
    report = tool(3.0, 1.8, **ratings)
    assert report["candidate_electrically_sufficient_on_paper"] is False
    assert report["candidate_physically_qualified"] is False
    assert report["charger_and_load_sharing_verified"] is False
    assert report["thermal_and_brownout_verified"] is False


def test_bq25895_otg_output_limit_cannot_be_confused_with_charge_current():
    # TI BQ25895 advertises 5 A charging, but its OTG boost output is
    # specified up to 3.1 A. Neither rating qualifies a particular board.
    # Full pet peak sizing requires 3.9 A at 5 V with the stated margin.
    report = tool(3.0, 1.8, boost_max_input_a=9.0,
                  boost_continuous_input_a=5.0,
                  boost_continuous_output_a=3.1,
                  protected_cell_continuous_a=9.0)
    assert report["minimum_rated_5v_output_a"] == 3.9
    assert report["candidate_electrically_sufficient_on_paper"] is False
    assert report["candidate_physically_qualified"] is False
    assert report["charger_and_load_sharing_verified"] is False


def test_bq25672_otg_limit_is_not_its_three_amp_charge_rating():
    # TI BQ25672 supports up to 3 A charging, but its OTG current
    # regulation is limited to 2 A. Neither figure qualifies the board.
    report = tool(3.0, 1.8, boost_max_input_a=9.0,
                  boost_continuous_input_a=5.0,
                  boost_continuous_output_a=2.0,
                  protected_cell_continuous_a=9.0)
    assert report["minimum_rated_5v_output_a"] == 3.9
    assert report["candidate_electrically_sufficient_on_paper"] is False
    assert report["candidate_physically_qualified"] is False
    assert report["charger_and_load_sharing_verified"] is False


def test_power_report_retains_both_original_load_measurements_for_audit():
    # Peak and sustained measurements must remain distinguishable from
    # derated minimum component ratings in a downstream shopping audit.
    report = tool(3.0, 1.8)
    assert report["measured_peak_5v_a"] == 3.0
    assert report["measured_continuous_5v_a"] == 1.8
    assert report["minimum_rated_5v_output_a"] > report["measured_peak_5v_a"]
    assert report["minimum_rated_continuous_5v_a"] > report["measured_continuous_5v_a"]
    assert report["candidate_physically_qualified"] is False
    assert report["charger_and_load_sharing_verified"] is False


def test_larger_safety_margin_cannot_turn_undersized_supply_into_qualified_candidate():
    # A board that clears a smaller arithmetic reserve must fail when the
    # required reserve grows; no charging or physical verdict follows either.
    ratings = dict(boost_max_input_a=5.0, boost_continuous_input_a=4.0,
                   boost_continuous_output_a=3.0, protected_cell_continuous_a=6.0)
    smaller = tool(2.0, 1.2, margin=1.0, **ratings)
    larger = tool(2.0, 1.2, margin=1.5, **ratings)
    assert smaller["candidate_electrically_sufficient_on_paper"] is True
    assert larger["candidate_electrically_sufficient_on_paper"] is False
    assert larger["minimum_rated_5v_output_a"] > smaller["minimum_rated_5v_output_a"]
    assert larger["minimum_rated_cell_and_boost_input_a"] > smaller["minimum_rated_cell_and_boost_input_a"]
    for report in (smaller, larger):
        assert report["candidate_physically_qualified"] is False
        assert report["charger_and_load_sharing_verified"] is False


def test_cli_margin_changes_paper_sizing(monkeypatch, capsys):
    # The CLI must honor the same explicit reserve as the Python sizing API.
    import json
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    for margin, expected in (("1.0", 2.0), ("1.5", 3.0)):
        monkeypatch.setattr(sys, "argv", [str(script), "--peak-5v-a", "2",
                            "--continuous-5v-a", "1.2", "--margin", margin])
        runpy.run_path(str(script), run_name="__main__")
        report = json.loads(capsys.readouterr().out)
        assert report["minimum_rated_5v_output_a"] == expected
        assert report["candidate_physically_qualified"] is False
        assert report["charger_and_load_sharing_verified"] is False


def test_tps61088_ten_amp_switch_rating_is_not_a_five_volt_output_rating():
    # TI TPS61088's 10 A figure describes its internal switching path,
    # not a verified 10 A continuous 5 V output from a particular board.
    # A candidate with only that advertised switch rating has no complete
    # published boost input/output and protected cell current specifications.
    unknown = tool(3.0, 1.8)
    assert unknown["minimum_rated_5v_output_a"] == 3.9
    assert unknown["candidate_electrically_sufficient_on_paper"] is None
    # Even a hypothetical board limited to 3 A continuous 5 V output fails
    # the simultaneous full robot peak despite generous other ratings.
    limited = tool(3.0, 1.8, boost_max_input_a=10,
                   boost_continuous_input_a=10,
                   boost_continuous_output_a=3,
                   protected_cell_continuous_a=10)
    assert limited["candidate_electrically_sufficient_on_paper"] is False
    assert limited["candidate_physically_qualified"] is False
    assert limited["charger_and_load_sharing_verified"] is False


def test_increased_sustained_load_cannot_pass_unchanged_continuous_input_rating():
    # Keep the same peak, low-cell voltage, efficiency and published ratings.
    # Only sustained simultaneous load grows; peak-capable hardware must
    # still fail when its continuous input thermal rating is insufficient.
    ratings = dict(boost_max_input_a=9.0, boost_continuous_input_a=3.0,
                   boost_continuous_output_a=4.0, protected_cell_continuous_a=9.0)
    lower = tool(3.0, 1.0, **ratings)
    higher = tool(3.0, 1.8, **ratings)
    assert lower["candidate_electrically_sufficient_on_paper"] is True
    assert higher["candidate_electrically_sufficient_on_paper"] is False
    assert higher["minimum_continuous_cell_input_a"] > lower["minimum_continuous_cell_input_a"]
    assert higher["minimum_rated_cell_and_boost_input_a"] == lower["minimum_rated_cell_and_boost_input_a"]
    for report in (lower, higher):
        assert report["candidate_physically_qualified"] is False
        assert report["charger_and_load_sharing_verified"] is False


def test_lower_cell_voltage_and_efficiency_cannot_improve_power_qualification():
    # Simultaneous worst case assumptions must increase required cell current,
    # even though the 5 V output load and the published ratings are unchanged.
    ratings = dict(boost_max_input_a=6.0, boost_continuous_input_a=4.0,
                   boost_continuous_output_a=4.0, protected_cell_continuous_a=6.0)
    nominal = tool(3.0, 1.8, cell_low_v=3.7,
                   measured_boost_efficiency=0.9, **ratings)
    worst = tool(3.0, 1.8, cell_low_v=3.0,
                 measured_boost_efficiency=0.75, **ratings)
    assert nominal["candidate_electrically_sufficient_on_paper"] is True
    assert worst["candidate_electrically_sufficient_on_paper"] is False
    assert worst["minimum_rated_cell_and_boost_input_a"] > nominal["minimum_rated_cell_and_boost_input_a"]
    assert worst["minimum_continuous_cell_input_a"] > nominal["minimum_continuous_cell_input_a"]
    assert worst["minimum_rated_5v_output_a"] == nominal["minimum_rated_5v_output_a"]
    for report in (nominal, worst):
        assert report["candidate_physically_qualified"] is False
        assert report["charger_and_load_sharing_verified"] is False


def test_bq25798_otg_current_limit_cannot_qualify_full_robot_peak():
    # TI BQ25798 permits up to 3.32 A OTG current regulation; its 5 A
    # battery charge rating is not a 5 V robot supply rating. These are
    # chip limits, not measured carrier-board or load-sharing evidence.
    report = tool(3.0, 1.8, boost_max_input_a=10.0,
                  boost_continuous_input_a=10.0,
                  boost_continuous_output_a=3.32,
                  protected_cell_continuous_a=10.0)
    assert report["minimum_rated_5v_output_a"] == 3.9
    assert report["candidate_electrically_sufficient_on_paper"] is False
    assert report["candidate_physically_qualified"] is False
    assert report["charger_and_load_sharing_verified"] is False


@pytest.mark.parametrize("flag,value", [
    ("--peak-5v-a", "nan"),
    ("--continuous-5v-a", "inf"),
    ("--low-cell-v", "nan"),
    ("--measured-efficiency", "inf"),
    ("--boost-max-input-a", "nan"),
    ("--protected-cell-continuous-a", "inf"),
    ("--margin", "nan"),
    ("--boost-continuous-input-a", "inf"),
    ("--boost-continuous-output-a", "-inf"),
])
def test_cli_rejects_nonfinite_power_telemetry_and_ratings(monkeypatch, capsys, flag, value):
    # A malformed machine-generated CLI argument must never yield a plausible
    # shopping qualification JSON report, including when a rating is optional.
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    argv = [str(script), "--peak-5v-a", "3", "--continuous-5v-a", "1.8",
            # argparse treats a standalone -inf token as another option.
            # Explicit flag=value tests the numeric safety validator itself.
            f"{flag}={value}"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError):
        runpy.run_path(str(script), run_name="__main__")
    assert capsys.readouterr().out == ""



@pytest.mark.parametrize("field", [
    "peak", "continuous", "cell_low_v", "measured_boost_efficiency",
    "margin", "boost_max_input_a", "boost_continuous_input_a",
    "boost_continuous_output_a", "protected_cell_continuous_a",
])
@pytest.mark.parametrize("bad", [True, False, "1.0"])
def test_power_api_rejects_untyped_or_boolean_sensor_readings(field, bad):
    # JSON booleans are Python integers, but cannot certify a measured current,
    # voltage, efficiency, margin or manufacturer current rating.
    if field == "peak":
        args, kwargs = (bad, 0.6), {}
    elif field == "continuous":
        args, kwargs = (1, bad), {}
    else:
        args, kwargs = (1, 0.6), {field: bad}
    with pytest.raises(ValueError):
        tool(*args, **kwargs)

@pytest.mark.parametrize("field", [
    "peak", "continuous", "cell_low_v", "measured_boost_efficiency",
    "margin", "boost_max_input_a", "boost_continuous_input_a",
    "boost_continuous_output_a", "protected_cell_continuous_a",
])
def test_unrepresentably_large_integer_telemetry_fails_closed(field):
    # math.isfinite(huge_int) itself raises OverflowError in CPython.
    # The public sizing API must reject it consistently as invalid input.
    huge = 10 ** 1000
    if field == "peak":
        args, kwargs = (huge, 0.6), {}
    elif field == "continuous":
        args, kwargs = (1, huge), {}
    else:
        args, kwargs = (1, 0.6), {field: huge}
    with pytest.raises(ValueError):
        tool(*args, **kwargs)


def test_docked_electronics_budget_must_not_inherit_undocked_motor_peak():
    # Separate hypothetical measured profiles; these are NOT dock or charger
    # measurements. A lower docked electronics budget cannot qualify a charger,
    # and must not overwrite the mobile motor and gripper supply requirement.
    mobile = tool(3.0, 1.8)
    docked_electronics = tool(0.8, 0.5)
    assert mobile["minimum_rated_5v_output_a"] == 3.9
    assert docked_electronics["minimum_rated_5v_output_a"] == 1.04
    assert mobile["minimum_rated_cell_and_boost_input_a"] > docked_electronics["minimum_rated_cell_and_boost_input_a"]
    for report in (mobile, docked_electronics):
        assert report["charger_and_load_sharing_verified"] is False
        assert report["candidate_physically_qualified"] is False
        assert report["physical_load_verified"] is False



def _qualified_dock_ratings():
    return {
        "measured_sys_v": 4.4, "measured_boost_efficiency": 0.85,
        "charger_variant": "BQ24074",
        "charger_input_limit_a": 1.5,
        "charger_board_thermal_input_a": 1.5,
        "dock_adapter_continuous_a": 3.0,
        "rated_5v_boost_continuous_a": 2.0,
        "protected_pack_max_charge_a": 1.0,
        "motors_confirmed_disarmed": True,
    }


@pytest.mark.parametrize("variant", ["BQ24074", "BQ24075"])
def test_direct_docked_load_rejects_fictional_bq2407x_two_amp_rating(variant):
    """The standalone API cannot evade the BQ2407x's 1.5A silicon limits."""
    ratings = _qualified_dock_ratings()
    ratings["charger_variant"] = variant
    ratings["charger_input_limit_a"] = 2.0
    with pytest.raises(ValueError, match="input limit cannot exceed 1.5A"):
        docked(.5, .25, **ratings)
    ratings["charger_input_limit_a"] = 1.5
    with pytest.raises(ValueError, match="charge request cannot exceed 1.5A"):
        docked(.5, 2.0, **ratings)
    assert docked(.5, .25, **ratings)[
        "candidate_docked_load_on_paper"
    ] in (True, False)


def test_direct_dock_api_refuses_missing_or_unknown_charger_identity():
    ratings = _qualified_dock_ratings()
    ratings.pop("charger_variant")
    with pytest.raises(ValueError, match="Explicit BQ24074 or BQ24075"):
        docked(.5, .25, **ratings)
    ratings["charger_variant"] = "BQ24073"
    with pytest.raises(ValueError, match="Explicit BQ24074 or BQ24075"):
        docked(.5, .25, **ratings)


def test_docked_idle_current_plus_real_charge_target_must_both_fit():
    small = docked(.5, .25, **_qualified_dock_ratings())
    assert small["candidate_docked_load_on_paper"] is True
    assert small["candidate_physically_qualified"] is False
    assert small["signed_battery_charge_current_measured"] is False
    # Camera, audio and a moving motor can take all available charger input.
    large = docked(1.0, .25, **_qualified_dock_ratings())
    assert large["minimum_sustained_dock_input_a"] > 1.5
    assert large["candidate_docked_load_on_paper"] is False
    assert large["charger_and_load_sharing_verified"] is False


@pytest.mark.parametrize("missing", [
    "charger_input_limit_a",
    "charger_board_thermal_input_a",
    "dock_adapter_continuous_a",
    "rated_5v_boost_continuous_a",
    "protected_pack_max_charge_a",
])
def test_docked_load_refuses_unspecified_carrier_or_pack_limit(missing):
    ratings = _qualified_dock_ratings()
    ratings.pop(missing)
    assert docked(.5, .25, **ratings)["candidate_docked_load_on_paper"] is None


@pytest.mark.parametrize("bottleneck,limit", [
    ("charger_input_limit_a", 1.0),
    ("charger_board_thermal_input_a", 1.0),
    ("dock_adapter_continuous_a", 1.0),
    ("rated_5v_boost_continuous_a", 0.5),
    ("protected_pack_max_charge_a", 0.25),
])
def test_docked_load_requires_every_independent_rating(bottleneck, limit):
    ratings = _qualified_dock_ratings()
    ratings[bottleneck] = limit
    result = docked(.5, .25, **ratings)
    assert result["candidate_docked_load_on_paper"] is False


@pytest.mark.parametrize("invalid", [
    True, 0, -1, float("nan"), float("inf"), 100,
])
def test_dock_current_reports_must_be_real_measurements(invalid):
    with pytest.raises(ValueError):
        docked(invalid, .25, **_qualified_dock_ratings())
    with pytest.raises(ValueError):
        docked(.5, invalid, **_qualified_dock_ratings())


def test_docked_charger_requires_motors_disarmed_but_not_full_approval():
    ratings = _qualified_dock_ratings()
    ratings["motors_confirmed_disarmed"] = False
    result = docked(.5, .25, **ratings)
    assert result["candidate_docked_load_on_paper"] is False
    assert result["candidate_physically_qualified"] is False
    ratings["motors_confirmed_disarmed"] = 1
    with pytest.raises(ValueError, match="explicit physical boolean"):
        docked(.5, .25, **ratings)


def test_docked_lower_sys_voltage_and_efficiency_never_ease_load():
    rated = _qualified_dock_ratings()
    baseline = docked(.5, .25, **rated)
    rated["measured_sys_v"] = 3.4
    depleted = docked(.5, .25, **rated)
    assert depleted["minimum_sustained_dock_input_a"] > (
        baseline["minimum_sustained_dock_input_a"])
    rated["measured_boost_efficiency"] = 0.6
    inefficient = docked(.5, .25, **rated)
    assert inefficient["minimum_sustained_dock_input_a"] > (
        depleted["minimum_sustained_dock_input_a"])




@pytest.mark.parametrize("dock_only", [
    ["--dock-charger-variant", "BQ24075"],
    ["--dock-regulator-topology", "buck_boost"],
    ["--dock-regulator-max-input-v", "22"],
    ["--dock-charger-input-limit-a", "1.5"],
    ["--dock-boost-5v-continuous-a", "2"],
    ["--dock-motors-disarmed"],
])
def test_stray_dock_options_never_silently_become_undocked_report(
    monkeypatch, capsys, dock_only,
):
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    argv = [
        str(script), "--peak-5v-a", "1", "--continuous-5v-a", "0.5",
    ] + dock_only
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(script), run_name="__main__")
    assert error.value.code == 2
    assert "Dock mode requires" in capsys.readouterr().err


def test_docked_cli_uses_exact_same_fail_closed_preflight(monkeypatch, capsys):
    import json
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    base = [
        str(script),
        "--dock-idle-5v-a", "0.5", "--dock-requested-charge-a", "0.25",
        "--dock-sys-v", "4.4", "--dock-boost-efficiency", "0.85",
        "--dock-charger-variant", "BQ24074",
        "--dock-regulator-topology", "boost_only",
        "--dock-regulator-min-input-v", "2.8",
        "--dock-regulator-max-input-v", "5.0",
        "--dock-charger-input-limit-a", "1.5",
        "--dock-board-thermal-input-a", "1.5",
        "--dock-adapter-continuous-a", "3",
        "--dock-boost-5v-continuous-a", "2",
        "--dock-pack-charge-max-a", "1",
    ]
    monkeypatch.setattr(sys, "argv", base)
    runpy.run_path(str(script), run_name="__main__")
    no_motion_proof = json.loads(capsys.readouterr().out)
    assert no_motion_proof["candidate_docked_load_on_paper"] is False
    monkeypatch.setattr(sys, "argv", base + ["--dock-motors-disarmed"])
    runpy.run_path(str(script), run_name="__main__")
    checked = json.loads(capsys.readouterr().out)
    assert checked["candidate_docked_load_on_paper"] is True
    assert checked["candidate_physically_qualified"] is False
    assert checked["signed_battery_charge_current_measured"] is False


def test_docked_cli_refuses_to_guess_which_charger_is_fitted(
    monkeypatch, capsys,
):
    import json
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    base = [
        "--dock-idle-5v-a", "0.5", "--dock-requested-charge-a", "0.25",
        "--dock-sys-v", "4.4", "--dock-boost-efficiency", "0.85",
        "--dock-motors-disarmed",
    ]
    monkeypatch.setattr(sys, "argv", [str(script)] + base)
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(script), run_name="__main__")
    assert error.value.code == 2
    for variant, max_v, topology, maximum in (
        ("BQ24074", 4.5, "boost_only", "5.0"),
        ("BQ24075", 5.6, "buck_boost", "22.0"),
    ):
        monkeypatch.setattr(
            sys, "argv", [str(script)] + base + [
                "--dock-charger-variant", variant,
                "--dock-regulator-topology", topology,
                "--dock-regulator-min-input-v", "2.8",
                "--dock-regulator-max-input-v", maximum,
            ],
        )
        runpy.run_path(str(script), run_name="__main__")
        report = json.loads(capsys.readouterr().out)
        assert report["charger_variant"] == variant
        assert report["charger_variant_max_docked_out_v"] == max_v
        assert report["voltage_path"]["regulator_covers_charger_output_on_paper"]
        assert report["candidate_physically_qualified"] is False


def test_docked_cli_never_approves_bq24075_with_boost_only_regulator(
    monkeypatch, capsys,
):
    import json
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    args = [
        "--dock-idle-5v-a", "0.5", "--dock-requested-charge-a", "0.25",
        "--dock-sys-v", "4.4", "--dock-boost-efficiency", "0.85",
        "--dock-charger-variant", "BQ24075",
        "--dock-regulator-topology", "boost_only",
        "--dock-regulator-min-input-v", "2.8",
        "--dock-regulator-max-input-v", "22.0",
        "--dock-charger-input-limit-a", "1.5",
        "--dock-board-thermal-input-a", "1.5",
        "--dock-adapter-continuous-a", "3",
        "--dock-boost-5v-continuous-a", "2",
        "--dock-pack-charge-max-a", "1", "--dock-motors-disarmed",
    ]
    monkeypatch.setattr(sys, "argv", [str(script)] + args)
    runpy.run_path(str(script), run_name="__main__")
    report = json.loads(capsys.readouterr().out)
    assert report["voltage_path"]["docked_output_max_v"] == 5.6
    assert not report["voltage_path"]["regulator_covers_charger_output_on_paper"]
    assert report["candidate_docked_load_on_paper"] is False
    assert report["candidate_physically_qualified"] is False


def test_cli_rejects_mixed_and_incomplete_power_modes(monkeypatch):
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    for arguments in (
        ["--dock-idle-5v-a", "0.5"],
        ["--dock-idle-5v-a", "0.5", "--dock-requested-charge-a", "0.2",
         "--dock-sys-v", "4.4", "--dock-boost-efficiency", "0.8",
         "--peak-5v-a", "1", "--continuous-5v-a", "0.5"],
        ["--peak-5v-a", "1"],
    ):
        monkeypatch.setattr(sys, "argv", [str(script)] + arguments)
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(script), run_name="__main__")
        assert result.value.code == 2


pack_screen = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
))["screen_protected_pack"]


def test_protected_pack_rejects_sustained_load_above_peak_requirement():
    # The vendor-specific screen already rejects this contradiction. The
    # reusable pack screen must not approve an invented inconsistent source.
    demand = tool(1.0, 0.6)
    peak = demand["minimum_rated_cell_and_boost_input_a"]
    demand["minimum_continuous_cell_input_a"] = peak + 0.001
    specs = dict(
        pack_length_mm=55, pack_width_mm=30, pack_thickness_mm=10,
        tray_length_mm=68, tray_width_mm=35, tray_height_mm=14,
        rated_peak_discharge_a=10, rated_continuous_discharge_a=10,
        pcm_overcurrent_trip_a=12, connector_continuous_a=10,
        wire_and_crimp_continuous_a=10,
    )
    with pytest.raises(ValueError, match="Continuous cell demand cannot exceed peak"):
        pack_screen(demand, **specs)
    demand["minimum_continuous_cell_input_a"] = peak
    allowed = pack_screen(demand, **specs)
    assert allowed["candidate_usable_on_paper"] is True
    assert allowed["candidate_physically_qualified"] is False


def test_protected_pack_envelope_and_current_screen_never_certifies_hardware():
    """No generic 2A pack or 86mm candidate is silently approved for 68mm tray."""
    requirements = tool(3, 1.8, cell_low_v=3.0, measured_boost_efficiency=.85)
    base = dict(
        tray_length_mm=68, tray_width_mm=35, tray_height_mm=14,
        rated_peak_discharge_a=10, rated_continuous_discharge_a=6,
        pcm_overcurrent_trip_a=11,
        connector_continuous_a=10, wire_and_crimp_continuous_a=10,
    )
    overlong = pack_screen(
        requirements, pack_length_mm=86, pack_width_mm=30,
        pack_thickness_mm=7.4, **base,
    )
    assert not overlong["assembled_pack_fits_tray_on_paper"]
    assert not overlong["candidate_usable_on_paper"]

    compact_but_underrated = pack_screen(
        requirements, pack_length_mm=55, pack_width_mm=30,
        pack_thickness_mm=10, **{
            **base, "rated_peak_discharge_a": 2,
            "rated_continuous_discharge_a": 2,
            "pcm_overcurrent_trip_a": 3,
        },
    )
    assert compact_but_underrated["assembled_pack_fits_tray_on_paper"]
    assert compact_but_underrated["current_sufficient_on_paper"] is False
    assert compact_but_underrated["candidate_usable_on_paper"] is False

    sufficient_hypothetical = pack_screen(
        requirements, pack_length_mm=55, pack_width_mm=30,
        pack_thickness_mm=10, **base,
    )
    assert sufficient_hypothetical["candidate_usable_on_paper"] is True
    assert sufficient_hypothetical["connector_and_wire_ratings_complete"]
    assert sufficient_hypothetical["connector_and_wire_current_sufficient_on_paper"]
    assert not sufficient_hypothetical["candidate_physically_qualified"]
    assert not sufficient_hypothetical["actual_pack_pcm_and_ntc_test_verified"]
    assert not sufficient_hypothetical["printed_assembly_and_wire_relief_verified"]


def test_identified_5a_86mm_pack_fails_conservative_three_amp_five_volt_case():
    """Manufacturer 5A MAX is not a guaranteed 5V 3A robot power solution.

    The 3A load is a stated design stress case, not a claimed measurement.
    Even if one OPTIMISTICALLY treats 5A as its sustained and PCM limit,
    its discharge rating and physical 68mm tray are insufficient.
    """
    demand = tool(3.0, 1.8, cell_low_v=3.0,
                  measured_boost_efficiency=0.85, margin=1.3)
    assert demand["minimum_rated_cell_and_boost_input_a"] > 7.64
    assert 5.0 < demand["minimum_rated_cell_and_boost_input_a"]
    result = pack_screen(
        demand, pack_length_mm=86.0, pack_width_mm=30.0,
        pack_thickness_mm=7.4, tray_length_mm=68.0,
        tray_width_mm=35.0, tray_height_mm=14.0,
        rated_peak_discharge_a=5.0,
        rated_continuous_discharge_a=5.0,
        pcm_overcurrent_trip_a=5.0,
    )
    assert result["assembled_pack_fits_tray_on_paper"] is False
    assert result["current_sufficient_on_paper"] is False
    assert result["candidate_usable_on_paper"] is False
    assert result["candidate_physically_qualified"] is False




def test_impossible_pack_envelope_is_false_even_without_current_ratings():
    # The assembled 86 mm pack cannot fit the 68 mm tray regardless of
    # whether its electrical ratings are known.
    demand = tool(1.0, 0.6)
    result = pack_screen(
        demand, pack_length_mm=86, pack_width_mm=30,
        pack_thickness_mm=7.4, tray_length_mm=68,
        tray_width_mm=35, tray_height_mm=14,
    )
    assert result["assembled_pack_fits_tray_on_paper"] is False
    assert result["current_sufficient_on_paper"] is None
    assert result["pack_only_usable_on_paper"] is False
    assert result["candidate_usable_on_paper"] is False
    assert result["candidate_physically_qualified"] is False


def test_protected_pack_incomplete_ratings_and_rotated_fit():
    requirements = tool(1.0, 0.6)
    base = dict(pack_length_mm=30, pack_width_mm=55,
                pack_thickness_mm=10, tray_length_mm=68,
                tray_width_mm=35, tray_height_mm=14)
    unknown = pack_screen(requirements, **base)
    assert unknown["assembled_pack_fits_tray_on_paper"]
    assert unknown["current_sufficient_on_paper"] is None
    assert unknown["candidate_usable_on_paper"] is None
    assert not unknown["candidate_physically_qualified"]


@pytest.mark.parametrize("field,value", [
    ("pack_length_mm", True),
    ("pack_length_mm", 10 ** 1000),
    ("tray_width_mm", -1),
    ("pack_thickness_mm", float("nan")),
    ("rated_continuous_discharge_a", True),
    ("pcm_overcurrent_trip_a", float("inf")),
    ("connector_continuous_a", float("nan")),
    ("wire_and_crimp_continuous_a", True),
    ("wire_and_crimp_continuous_a", -1),
])
def test_protected_pack_bad_specs_fail_closed(field, value):
    requirements = tool(1.0, 0.6)
    args = dict(pack_length_mm=55, pack_width_mm=30,
                pack_thickness_mm=10, tray_length_mm=68,
                tray_width_mm=35, tray_height_mm=14,
                rated_peak_discharge_a=8,
                rated_continuous_discharge_a=5,
                pcm_overcurrent_trip_a=9)
    args[field] = value
    with pytest.raises(ValueError):
        pack_screen(requirements, **args)


def test_pack_geometry_cli_rejects_an_overlong_cell_before_order(monkeypatch, capsys):
    import json
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    base = [str(script), "--peak-5v-a", "3",
            "--continuous-5v-a", "1.8", "--pack-length-mm", "86",
            "--pack-width-mm", "30", "--pack-thickness-mm", "7.4",
            "--tray-length-mm", "68", "--tray-width-mm", "35",
            "--tray-height-mm", "14", "--pack-peak-discharge-a", "10",
            "--pack-continuous-discharge-a", "6", "--pack-pcm-trip-a", "11"]
    monkeypatch.setattr(sys, "argv", base)
    runpy.run_path(str(script), run_name="__main__")
    result = json.loads(capsys.readouterr().out)
    assert result["protected_pack_screen"]["assembled_pack_fits_tray_on_paper"] is False
    assert result["protected_pack_screen"]["candidate_usable_on_paper"] is False
    assert result["protected_pack_screen"]["candidate_physically_qualified"] is False
    # A shorter envelope may pass ONLY the math. The actual pack is never
    # called qualified by the CLI even when every hypothetical rating fits.
    changed = list(base)
    changed[changed.index("--pack-length-mm") + 1] = "55"
    changed += ["--pack-connector-continuous-a", "10",
                "--pack-wire-crimp-continuous-a", "10"]
    monkeypatch.setattr(sys, "argv", changed)
    runpy.run_path(str(script), run_name="__main__")
    good = json.loads(capsys.readouterr().out)
    assert good["protected_pack_screen"]["candidate_usable_on_paper"] is True
    assert good["protected_pack_screen"]["candidate_physically_qualified"] is False


def test_pack_cli_requires_all_geometry_and_undocked_mode(monkeypatch):
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    for params in (
        ["--peak-5v-a", "1", "--continuous-5v-a", ".6",
         "--pack-length-mm", "55"],
        ["--dock-idle-5v-a", ".5", "--dock-requested-charge-a", ".25",
         "--dock-sys-v", "4.4", "--dock-boost-efficiency", ".85",
         "--pack-length-mm", "55", "--pack-width-mm", "30",
         "--pack-thickness-mm", "10", "--tray-length-mm", "68",
         "--tray-width-mm", "35", "--tray-height-mm", "14"],
    ):
        monkeypatch.setattr(sys, "argv", [str(script)] + params)
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(script), run_name="__main__")
        assert exc.value.code == 2


@pytest.mark.parametrize("flag,value", [
    ("--pack-wire-relief-mm", "-5"),
    ("--pack-side-clearance-mm", "3"),
])
def test_pack_cli_standalone_clearance_must_not_skip_pack_screen(
    monkeypatch, flag, value,
):
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    monkeypatch.setattr(sys, "argv", [
        str(script), "--peak-5v-a", "1", "--continuous-5v-a", ".6",
        flag, value,
    ])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(script), run_name="__main__")
    assert exc.value.code == 2


@pytest.mark.parametrize("extra,expected_fit", [
    ([], True),
    (["--pack-wire-relief-mm", "12"], False),
    (["--pack-side-clearance-mm", "3"], False),
    (["--pack-wire-relief-mm", "3", "--pack-side-clearance-mm", "1"], True),
])
def test_pack_cli_clearances_reach_assembled_envelope(
    monkeypatch, capsys, extra, expected_fit,
):
    import json
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    monkeypatch.setattr(sys, "argv", [
        str(script), "--peak-5v-a", "1", "--continuous-5v-a", ".6",
        "--pack-length-mm", "55", "--pack-width-mm", "30",
        "--pack-thickness-mm", "10", "--tray-length-mm", "68",
        "--tray-width-mm", "35", "--tray-height-mm", "14",
        *extra,
    ])
    runpy.run_path(str(script), run_name="__main__")
    report = json.loads(capsys.readouterr().out)["protected_pack_screen"]
    assert report["assembled_pack_fits_tray_on_paper"] is expected_fit
    assert report["candidate_physically_qualified"] is False


@pytest.mark.parametrize("peak,continuous,trip", [
    (8, 9, 10),
    (10, 6, 9),
    (10, 11, 9),
])
def test_pack_pcm_rating_must_cover_its_own_advertised_peak(peak, continuous, trip):
    """Reject contradictory seller ratings before treating a cell as compatible."""
    demand = tool(1, 0.6)
    with pytest.raises(ValueError, match="Contradictory protected pack"):
        pack_screen(
            demand,
            pack_length_mm=55, pack_width_mm=30, pack_thickness_mm=10,
            tray_length_mm=68, tray_width_mm=35, tray_height_mm=14,
            rated_peak_discharge_a=peak,
            rated_continuous_discharge_a=continuous,
            pcm_overcurrent_trip_a=trip,
        )


def test_real_4a_cell_does_not_override_a_0_86a_or_2_2a_connector():
    """BatterySpace supplies multiple actual connector ratings for one 4A cell.

    These are illustrative manufacturer ratings, not approval to buy that pack.
    At a hypothetical 5V 1A peak, minimum 1S input is 2.550A with margin.
    """
    demand = tool(1, .6)
    assert demand["minimum_rated_cell_and_boost_input_a"] == 2.55
    base = dict(pack_length_mm=55, pack_width_mm=30,
                pack_thickness_mm=10, tray_length_mm=68,
                tray_width_mm=35, tray_height_mm=14,
                rated_peak_discharge_a=4, rated_continuous_discharge_a=4,
                pcm_overcurrent_trip_a=5)
    unknown = pack_screen(demand, **base)
    assert unknown["pack_only_usable_on_paper"] is True
    assert unknown["connector_and_wire_ratings_complete"] is False
    assert unknown["candidate_usable_on_paper"] is None
    for amps in (.86, 2.2):
        report = pack_screen(
            demand, connector_continuous_a=amps,
            wire_and_crimp_continuous_a=amps, **base)
        assert report["pack_only_usable_on_paper"] is True
        assert report["connector_and_wire_current_sufficient_on_paper"] is False
        assert report["candidate_usable_on_paper"] is False
        assert report["candidate_physically_qualified"] is False
    hypothetical = pack_screen(
        demand, connector_continuous_a=4,
        wire_and_crimp_continuous_a=4, **base)
    assert hypothetical["candidate_usable_on_paper"] is True
    assert hypothetical["candidate_physically_qualified"] is False


def test_one_missing_harness_spec_and_cli_cannot_claim_compatible(monkeypatch, capsys):
    import json
    import sys
    demand = tool(1, .6)
    base = dict(pack_length_mm=55, pack_width_mm=30,
                pack_thickness_mm=10, tray_length_mm=68,
                tray_width_mm=35, tray_height_mm=14,
                rated_peak_discharge_a=8, rated_continuous_discharge_a=5,
                pcm_overcurrent_trip_a=9)
    assert pack_screen(
        demand, connector_continuous_a=8, **base)[
        "candidate_usable_on_paper"] is None
    script = Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
    args = [str(script), "--peak-5v-a", "1",
            "--continuous-5v-a", ".6",
            "--pack-length-mm", "55", "--pack-width-mm", "30",
            "--pack-thickness-mm", "10", "--tray-length-mm", "68",
            "--tray-width-mm", "35", "--tray-height-mm", "14",
            "--pack-peak-discharge-a", "8",
            "--pack-continuous-discharge-a", "5",
            "--pack-pcm-trip-a", "9",
            "--pack-connector-continuous-a", "8"]
    monkeypatch.setattr(sys, "argv", args)
    runpy.run_path(str(script), run_name="__main__")
    result = json.loads(capsys.readouterr().out)
    assert result["protected_pack_screen"]["candidate_usable_on_paper"] is None
    args += ["--pack-wire-crimp-continuous-a", ".86"]
    monkeypatch.setattr(sys, "argv", args)
    runpy.run_path(str(script), run_name="__main__")
    unsafe = json.loads(capsys.readouterr().out)
    assert unsafe["protected_pack_screen"]["candidate_usable_on_paper"] is False


one_stack = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
))["screen_one_cell_power_stack"]


def plausible_hypothetical_one_cell_stack():
    """All invented values solely prove gate logic, NOT a real SKU selection."""
    return dict(
        active_peak_5v_a=.6, active_sustained_5v_a=.4,
        dock_idle_5v_a=.2, charge_request_a=.4,
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
    )


def test_full_power_stack_refuses_implicit_or_unknown_fitted_charger():
    cfg = plausible_hypothetical_one_cell_stack()
    cfg.pop("charger_variant")
    with pytest.raises(ValueError, match="source-reviewed BQ24074 or BQ24075"):
        one_stack(**cfg)
    cfg["charger_variant"] = "BQ24073"
    with pytest.raises(ValueError, match="source-reviewed BQ24074 or BQ24075"):
        one_stack(**cfg)


def test_complete_one_cell_stack_proves_only_math_not_battery_safety():
    result = one_stack(**plausible_hypothetical_one_cell_stack())
    assert result["charger_variant"] == "BQ24075"
    assert result["all_power_stages_compatible_on_paper"] is True
    assert all(result["checks"].values())
    assert result["all_power_stages_physically_verified"] is False
    assert result["qualified_1s_dock_safe_to_buy"] is False
    assert result["battery_and_harness"]["candidate_physically_qualified"] is False
    assert result["docked"]["charger_and_load_sharing_verified"] is False


def test_stack_rejects_wrong_regulator_only_rated_at_five_volts():
    cfg = plausible_hypothetical_one_cell_stack()
    # Pololu #4082 is marketed 3A only for input close to 5V.
    # With the genuine 3V graph missing this cannot pass full robot review.
    cfg["boost_output_at_3v_continuous_a"] = None
    assert not one_stack(**cfg)["all_power_stages_compatible_on_paper"]
    cfg["boost_output_at_3v_continuous_a"] = 0.5
    assert not one_stack(**cfg)["all_power_stages_compatible_on_paper"]


def test_stack_rejects_boost_only_even_with_wide_input_rating():
    cfg = plausible_hypothetical_one_cell_stack()
    cfg["regulator_topology"] = "boost_only"
    result = one_stack(**cfg)
    assert not result["voltage_path"]["topology_supports_regulating_5v_both_modes"]
    assert not result["checks"]["charger_out_to_regulated_5v_covers_3v_cell_and_dock"]
    assert not result["all_power_stages_compatible_on_paper"]
    assert not result["qualified_1s_dock_safe_to_buy"]


def test_stack_rejects_5v_only_regulator_on_bq24075_dock():
    cfg = plausible_hypothetical_one_cell_stack()
    cfg["boost_regulator_max_input_v"] = 5.0
    result = one_stack(**cfg)
    assert not result["checks"][
        "charger_out_to_regulated_5v_covers_3v_cell_and_dock"]
    assert not result["all_power_stages_compatible_on_paper"]


def test_stack_does_not_ignore_actual_ntc_jumper_and_connector():
    cfg = plausible_hypothetical_one_cell_stack()
    cfg["connector_a"] = 0.86
    result = one_stack(**cfg)
    assert not result["checks"]["whole_protected_cell_pcm_cable_and_tray"]
    cfg["connector_a"] = 8
    cfg["charger_ts_fixed_resistor_removed"] = False
    result = one_stack(**cfg)
    assert not result["checks"]["charger_ts_is_connected_to_actual_pack_ntc"]
    cfg["charger_ts_fixed_resistor_removed"] = True
    cfg["charge_temperature_sensor_connected"] = False
    assert not one_stack(**cfg)["all_power_stages_compatible_on_paper"]


def test_stack_will_not_count_1_5a_bq24075_twice():
    cfg = plausible_hypothetical_one_cell_stack()
    cfg["charger_input_limit_a"] = 2.0
    with pytest.raises(ValueError, match="not above 1.5"):
        one_stack(**cfg)
    cfg["charger_input_limit_a"] = 1.4
    cfg["dock_idle_5v_a"] = 1.3
    # 1.3 A system output plus 0.4 A charge cannot fit a 1.4A charger.
    assert not one_stack(**cfg)["checks"][
        "docked_idle_plus_cell_charge_in_same_1_5a_budget"]


def test_stack_requires_disarmed_motors_and_actual_pack_volume():
    cfg = plausible_hypothetical_one_cell_stack()
    cfg["dock_motors_disarmed"] = False
    assert not one_stack(**cfg)["all_power_stages_compatible_on_paper"]
    cfg["dock_motors_disarmed"] = True
    cfg["pack_mm"] = (70, 50, 20)
    assert not one_stack(**cfg)["checks"]["whole_protected_cell_pcm_cable_and_tray"]
    cfg["pack_mm"] = (50, 30, 10)
    cfg["pack_sustained_a"] = None
    assert not one_stack(**cfg)["all_power_stages_compatible_on_paper"]



def test_published_lp103650_short_pack_is_still_too_wide_and_underrated():
    """A shorter 51 mm pack is not a substitute for validated geometry/current.

    Published LP103650 protected 1S: 10 x 36 x 51 mm, 2 A maximum discharge.
    Source: lipobattery.us LP103650 page. Model 68 x 35 x 14 mm tray from
    docs/cad/remixes/remaining_fit_gauges.scad, 1 mm side clearances,
    and original conservative 3 A @5V, 3 V low-cell, 85% boost.
    """
    requirement = tool(3.0, 1.8, cell_low_v=3.0,
                       measured_boost_efficiency=0.85)
    verdict = pack_screen(
        requirement, pack_length_mm=51, pack_width_mm=36,
        pack_thickness_mm=10, tray_length_mm=68, tray_width_mm=35,
        tray_height_mm=14, rated_peak_discharge_a=2.0,
        rated_continuous_discharge_a=2.0, pcm_overcurrent_trip_a=2.0)
    assert requirement["minimum_rated_cell_and_boost_input_a"] > 7.6
    assert verdict["assembled_pack_fits_tray_on_paper"] is False
    assert verdict["current_sufficient_on_paper"] is False
    assert verdict["candidate_usable_on_paper"] is False
    assert verdict["candidate_physically_qualified"] is False
