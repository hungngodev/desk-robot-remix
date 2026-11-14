"""Electrical arithmetic only, never substitutes for measuring hardware."""
import runpy
from pathlib import Path

import pytest

tool = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/power_preflight.py"
))["size_5v_supply"]


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
