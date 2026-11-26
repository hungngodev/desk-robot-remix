"""Vendor specifications cannot qualify a delivered battery harness."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/screen_vendor_battery_harness.py"
DEMAND = {"minimum_rated_cell_and_boost_input_a": 1.0,
          "minimum_continuous_cell_input_a": 0.5}
MODEL = "NX-MGL00850-1S2P"
ROLES = {"pin_1": "negative", "pin_2": "ntc", "pin_3": "positive"}


@pytest.fixture
def screen():
    spec = importlib.util.spec_from_file_location("vendor_screen", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("ntc", [None, "optional", "100k", True, "missing"])
def test_missing_or_unqualified_ntc_stays_on_hold(screen, monkeypatch, ntc):
    pack = dict(screen.catalog()[MODEL])
    if ntc == "missing":
        pack.pop("ntc")
    else:
        pack["ntc"] = ntc
    monkeypatch.setitem(screen._PACKS, MODEL, pack)
    result = screen.evaluate(MODEL, DEMAND, tray_mm=(100, 60, 30))
    assert "pack_ntc_10k_not_fitted_in_exact_variant" in result["blocking_reasons"]
    assert result["complete_power_path_safe_to_buy"] is False


@pytest.mark.parametrize("pcm", [False, None, 1, "missing", True])
def test_paper_fit_and_matching_pinout_never_qualify_pack(screen, monkeypatch, pcm):
    pack = {**screen.catalog()[MODEL], "connector": "JST-PH-3",
            "terminal_roles": tuple(ROLES.items()), "connector_continuous_a": 2.0,
            "lead_continuous_a": 2.0}
    if pcm == "missing":
        pack.pop("pcm")
    else:
        pack["pcm"] = pcm
    monkeypatch.setitem(screen._PACKS, MODEL, pack)
    result = screen.evaluate(
        MODEL, DEMAND, tray_mm=(100, 60, 30), expected_connector="JST-PH-3",
        expected_terminal_roles=ROLES,
    )
    assert result["pack_fits_current_tray_on_paper"] is True
    assert result["harness_ampacity_enough_on_paper"] is True
    assert result["connector_matches_selected_harness_on_paper"] is True
    assert result["pack_current_enough_on_paper"] is (pcm is True)
    assert result["physical_harness_wiring_verified"] is False
    assert result["complete_power_path_safe_to_buy"] is False
    assert {"physical_pack_protection_not_verified", "physical_pack_ntc_not_verified",
            "fuel_gauge_not_qualified"} <= set(result["blocking_reasons"])


def test_all_catalog_candidates_hold_even_with_large_tray(screen):
    for model in screen.catalog():
        result = screen.evaluate(model, DEMAND, tray_mm=(120, 80, 40))
        assert result["complete_power_path_safe_to_buy"] is False
        assert result["physical_harness_wiring_verified"] is False
        assert {"physical_pack_protection_not_verified", "physical_pack_ntc_not_verified",
                "fuel_gauge_not_qualified"} <= set(result["blocking_reasons"])
