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


def test_exact_ten_vendor_variants_and_unchanged_power_sizing_source():
    screen = module("screen_vendor_battery_harness")
    sizing = module("power_preflight")
    demand = sizing.size_5v_supply(1.0, 0.6)
    assert len(screen.catalog()) == 10
    assert demand["minimum_rated_cell_and_boost_input_a"] == 2.55
    for model in screen.catalog():
        report = screen.evaluate(model, demand)
        assert report["vendor_source"].startswith("https://")
        assert report["protected"] is True
        if model != "THOR-18650-1S2P-5200":
            assert report["ntc"] == "10k"
        else:
            assert report["ntc"] == "optional"
            assert "pcm_current_limit_and_connector_configuration_unselected" in report["blocking_reasons"]
        assert report["complete_power_path_safe_to_buy"] is False
        assert "charger_ntc_circuit_not_qualified" in report["blocking_reasons"]
        assert "physical_power_and_fit_trials_not_executed" in report["blocking_reasons"]


def test_overlong_five_amp_pack_and_compact_underrated_pack_rejected():
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1.0, 0.6)
    long_pack = screen.evaluate("LPHD7430085", demand)
    assert long_pack["pack_peak_within_published_max_on_paper"] is True
    assert long_pack["pack_current_enough_on_paper"] is None
    assert "manufacturer_continuous_discharge_rating_missing" in long_pack["blocking_reasons"]
    assert long_pack["pack_fits_current_tray_on_paper"] is False
    assert "exact_connector_or_lead_ampacity_missing" in long_pack["blocking_reasons"]
    compact = screen.evaluate("LP103650", demand)
    assert compact["pack_peak_within_published_max_on_paper"] is False
    assert compact["pack_current_enough_on_paper"] is None
    assert compact["pack_fits_current_tray_on_paper"] is False
    assert "pack_max_discharge_below_peak_budget" in compact["blocking_reasons"]


def test_same_4a_cell_but_different_pack_connector_current_limit():
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1.0, 0.6)
    bare = screen.evaluate("PR-CU-R512-22AWG", demand)
    jst30 = screen.evaluate("PR-CU-R512-JST-SHR", demand)
    molex26 = screen.evaluate("PR-CU-R512-Molex-26AWG", demand)
    assert all(r["pack_peak_within_published_max_on_paper"]
               for r in (bare, jst30, molex26))
    assert all(r["pack_current_enough_on_paper"] is None
               for r in (bare, jst30, molex26))
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



def test_forged_continuous_demand_above_peak_cannot_show_pack_as_adequate():
    screen = module("screen_vendor_battery_harness")
    # A profile assembled from inconsistent measurements must not say that
    # a sourced 3.4 A pack is electrically adequate even on paper.
    contradictory = {
        "minimum_rated_cell_and_boost_input_a": 1.0,
        "minimum_continuous_cell_input_a": 2.5,
    }
    with pytest.raises(ValueError, match="Continuous battery demand exceeds peak"):
        screen.evaluate("NX-MGL00850-1S2P", contradictory,
                        tray_mm=(90, 46, 25))
    equal_peak = {**contradictory,
                  "minimum_rated_cell_and_boost_input_a": 2.5}
    result = screen.evaluate("NX-MGL00850-1S2P", equal_peak,
                             tray_mm=(90, 46, 25))
    assert result["pack_current_enough_on_paper"] is True
    assert result["complete_power_path_safe_to_buy"] is False


def test_unknown_pack_and_invalid_tray_dimensions_rejected():
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1.0, .6)
    with pytest.raises(ValueError, match="Unknown"):
        screen.evaluate("anonymous-2000mah", demand)
    for dims in ((True, 35, 14), (0, 35, 14), (68, -35, 14), (68, 35, float("inf"))):
        with pytest.raises(ValueError):
            screen.evaluate("LPHD7430085", demand, tray_mm=dims)


def test_new_verified_large_pack_continuous_ratings_reject_false_10a_claims():
    """Two parallel cells can still ship with a 2A or 2.5A PCM.

    A bare cell's advertised 10.4A theoretical maximum is NOT the actual
    protection circuit, connector or whole assembled pack continuous rate.
    """
    screen = module("screen_vendor_battery_harness")
    supply = module("power_preflight").size_5v_supply(2.0, 1.2)
    assert supply["minimum_rated_cell_and_boost_input_a"] > 5
    varta = screen.evaluate("VARTA-VAR56653502013", supply,
                            tray_mm=(115, 55, 30))
    litech = screen.evaluate("LITECH-LP1S2P2A2AL005", supply,
                             tray_mm=(115, 55, 30))
    for report, _sustained in ((varta, 2.5), (litech, 2.0)):
        assert report["pack_fits_current_tray_on_paper"]
        assert report["pack_peak_within_published_max_on_paper"] is False
        assert report["pack_current_enough_on_paper"] is False
        assert "pack_max_discharge_below_peak_budget" in report["blocking_reasons"]
        assert "pack_current_rating_below_load_budget" in report["blocking_reasons"]
        assert report["complete_power_path_safe_to_buy"] is False
    thor = screen.evaluate("THOR-18650-1S2P-5200", supply,
                           tray_mm=(115, 55, 30))
    assert thor["pack_peak_within_published_max_on_paper"] is None
    assert thor["cell_level_max_discharge_a"] == 10.4
    assert thor["assembled_pack_mm"] is None
    assert thor["bare_pack_mm"] == (65.0, 37.0, 18.4)
    assert "manufacturer_assembled_pack_peak_discharge_rating_missing" in thor["blocking_reasons"]
    assert thor["pack_current_enough_on_paper"] is None
    assert thor["ntc"] == "optional"
    assert "pack_ntc_10k_not_fitted_in_exact_variant" in thor["blocking_reasons"]
    assert "bare_cell_envelope_not_complete_protected_pack" in thor["blocking_reasons"]
    assert thor["pack_fits_current_tray_on_paper"] is None
    assert "full_protected_pack_dimensions_unknown" in thor["blocking_reasons"]
    assert "protected_pack_does_not_fit_existing_cavity" not in thor["blocking_reasons"]


def test_wider_batteryspace_3000mah_does_not_fit_old_tray_or_claim_5a_continuous():
    screen = module("screen_vendor_battery_harness")
    supply = module("power_preflight").size_5v_supply(1, .6)
    report = screen.evaluate("BATTERYSPACE-CU-JAS427", supply)
    assert report["pack_fits_current_tray_on_paper"] is False
    assert report["pack_current_enough_on_paper"] is None
    assert report["pack_peak_within_published_max_on_paper"]
    assert report["harness_ampacity_enough_on_paper"] is False
    assert report["complete_power_path_safe_to_buy"] is False


def test_nx_one_s_two_p_real_pcm_rating_is_not_bare_cell_and_not_harness():
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1, 0.6)
    result = screen.evaluate("NX-MGL00850-1S2P", demand)
    assert result["pack_peak_within_published_max_on_paper"] is True
    assert result["pack_current_enough_on_paper"] is True
    assert result["pack_fits_current_tray_on_paper"] is False
    assert result["harness_ampacity_enough_on_paper"] is False
    assert "exact_connector_or_lead_ampacity_missing" in result["blocking_reasons"]
    assert result["complete_power_path_safe_to_buy"] is False
    demand = module("power_preflight").size_5v_supply(2, 1.2)
    high = screen.evaluate("NX-MGL00850-1S2P", demand, tray_mm=(90, 46, 25))
    assert high["pack_peak_within_published_max_on_paper"] is False
    assert high["pack_current_enough_on_paper"] is False


def test_default_battery_fit_screen_reads_current_cad_tray_not_stale_constants(
    tmp_path, monkeypatch,
):
    screen = module("screen_vendor_battery_harness")
    demand = module("power_preflight").size_5v_supply(1.0, 0.6)
    # CAD now excludes a cavity shorter than the 86mm candidate pack body.
    # Even this cavity is NOT enough for the pack and lead bend relief.
    assert screen.cad_tray_mm() == (86.0, 35.0, 14.0)
    original = screen._TRAY_CAD.read_text(encoding="utf-8")
    revised_cad = tmp_path / "remaining_fit_gauges.scad"
    revised_cad.write_text(
        original.replace("power_l = 86;", "power_l = 100;")
                .replace("power_w = 35;", "power_w = 38;")
                .replace("power_h = 14;", "power_h = 15;"),
        encoding="utf-8",
    )
    read_cad = screen.cad_tray_mm
    assert read_cad(revised_cad) == (100.0, 38.0, 15.0)
    monkeypatch.setattr(screen, "cad_tray_mm", lambda: read_cad(revised_cad))
    result = screen.evaluate("LPHD7430085", demand)
    assert result["pack_fits_current_tray_on_paper"] is True
    assert result["complete_power_path_safe_to_buy"] is False
    revised_cad.write_text("power_l = 100; power_l = 120;")
    with pytest.raises(ValueError, match="Missing or ambiguous"):
        read_cad(revised_cad)


@pytest.mark.parametrize(("peak", "expected"), [(0.5, None), (10.4, None), (10.401, False)])
def test_thor_cell_ceiling_never_proves_assembled_pack_peak(peak, expected):
    screen = module("screen_vendor_battery_harness")
    report = screen.evaluate(
        "THOR-18650-1S2P-5200",
        {"minimum_rated_cell_and_boost_input_a": peak,
         "minimum_continuous_cell_input_a": 0.5},
        tray_mm=(115, 55, 30),
    )
    assert report["pack_peak_within_published_max_on_paper"] is expected
    assert report["pack_current_enough_on_paper"] is None
    assert "manufacturer_assembled_pack_peak_discharge_rating_missing" in report["blocking_reasons"]
    assert ("cell_level_discharge_below_peak_budget" in report["blocking_reasons"]) == (expected is False)
    assert report["complete_power_path_safe_to_buy"] is False
