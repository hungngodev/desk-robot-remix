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
        3, 1.8, boost_max_input_a=5,
        boost_continuous_output_a=5, protected_cell_continuous_a=10,
    )
    assert bad["candidate_electrically_sufficient_on_paper"] is False
    generous = tool(
        1, .6, boost_max_input_a=5,
        boost_continuous_output_a=3, protected_cell_continuous_a=5,
    )
    assert generous["candidate_electrically_sufficient_on_paper"] is True
    assert generous["candidate_physically_qualified"] is False


@pytest.mark.parametrize("peak,average", [(0, 1), (1, 2), (-1, 1), (float("nan"), 1)])
def test_power_sizing_rejects_absent_and_bad_loads(peak, average):
    with pytest.raises(ValueError):
        tool(peak, average)
