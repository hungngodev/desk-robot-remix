"""Regression: cell datasheet is not connector, NTC, dock, or full robot approval."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "scripts"


def module(name):
    path = ROOT / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_exact_five_vendor_variants_and_unchanged_power_sizing_source():
    screen = module("screen_vendor_battery_harness")
    sizing = module("power_preflight")
    demand = sizing.size_5v_supply(1.0, 0.6)
    assert len(screen.catalog()) == 5
    assert demand["minimum_rated_cell_and_boost_input_a"] == 2.55
    for model in screen.catalog():
        report = screen.evaluate(model, demand)
        assert report["vendor_source"].startswith("https://")
        assert report["protected"] is True
        assert report["ntc"] == "10k"
        assert report["complete_power_path_safe_to_buy"] is False
        assert "charger_ntc_circuit_not_qualified" in report["blocking_reasons"]
        assert "physical_power_and_fit_trials_not_executed" in report["blocking_reasons"]


def test_overlong_five_amp_pack_and_compact_underrated_pack_rejected():
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1.0, 0.6)
    long_pack = screen.evaluate("LPHD7430085", demand)
    assert long_pack["pack_current_enough_on_paper"] is True
    assert long_pack["pack_fits_current_tray_on_paper"] is False
    assert "exact_connector_or_lead_ampacity_missing" in long_pack["blocking_reasons"]
    compact = screen.evaluate("LP103650", demand)
    assert compact["pack_current_enough_on_paper"] is False
    assert compact["pack_fits_current_tray_on_paper"] is False
    assert "pack_current_rating_below_load_budget" in compact["blocking_reasons"]


def test_same_4a_cell_but_different_pack_connector_current_limit():
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1.0, 0.6)
    bare = screen.evaluate("PR-CU-R512-22AWG", demand)
    jst30 = screen.evaluate("PR-CU-R512-JST-SHR", demand)
    molex26 = screen.evaluate("PR-CU-R512-Molex-26AWG", demand)
    assert all(r["pack_current_enough_on_paper"] for r in (bare, jst30, molex26))
    assert "exact_connector_or_lead_ampacity_missing" in bare["blocking_reasons"]
    assert "exact_connector_or_lead_ampacity_insufficient" in jst30["blocking_reasons"]
    assert "exact_connector_or_lead_ampacity_insufficient" in molex26["blocking_reasons"]
    assert jst30["harness_ampacity_enough_on_paper"] is False
    assert molex26["harness_ampacity_enough_on_paper"] is False
    # Changing a cell's 4A rating cannot erase 0.86A connector derating.
    assert screen.catalog()["PR-CU-R512-JST-SHR"]["connector_continuous_a"] == 0.86


def test_tray_redesign_does_not_fake_electrical_and_thermal_acceptance():
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1.0, 0.6)
    revised = screen.evaluate("LPHD7430085", demand, tray_mm=(100, 38, 15))
    assert revised["pack_fits_current_tray_on_paper"] is True
    assert revised["harness_ampacity_enough_on_paper"] is False
    assert revised["complete_power_path_safe_to_buy"] is False


@pytest.mark.parametrize("invalid", [
    None, {}, {"minimum_rated_cell_and_boost_input_a": True,
               "minimum_continuous_cell_input_a": 1},
    {"minimum_rated_cell_and_boost_input_a": float("nan"),
     "minimum_continuous_cell_input_a": 1},
])
def test_bad_or_fake_load_receipts_are_rejected(invalid):
    with pytest.raises(ValueError, match="valid measured-load"):
        module("screen_vendor_battery_harness").evaluate("LP103650", invalid)


def test_unknown_pack_and_invalid_tray_dimensions_rejected():
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1.0, .6)
    with pytest.raises(ValueError, match="Unknown"):
        screen.evaluate("anonymous-2000mah", demand)
    for dims in ((True, 35, 14), (0, 35, 14), (68, -35, 14), (68, 35, float("inf"))):
        with pytest.raises(ValueError):
            screen.evaluate("LPHD7430085", demand, tray_mm=dims)
