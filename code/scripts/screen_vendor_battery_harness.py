"""Manufacturer sourced 1S candidates versus the robot's whole harness.

This screen purposely cannot authorize an order. It uses the pre-existing
power_preflight sizing math and refuses to assume a high discharge pack also
has a high current connector, wire or correctly fitted PCM/NTC.
No battery vendor listed here is a recommendation to buy without trials.
"""
from __future__ import annotations

import argparse
import json
import re
import runpy
from pathlib import Path

_PACKS = {
    "LP103650": {
        "source": "https://www.lipobattery.us/3-7v-lipo-battery-lp103650-2000mah-7-4wh-with-pcm-and-wires-and-ntc-and-2510-3p/",
        "size_mm": (51.0, 36.0, 10.0),
        "continuous_a": None, "max_discharge_a": 2.0,
        "ntc": "10k", "pcm": True,
        "connector": "2510-3P", "connector_continuous_a": None,
        "lead_continuous_a": None,
    },
    "LPHD7430085": {
        "source": "https://lipo-battery.com/high-rate-discharge-lipo-battery-lphd7430085-5a-3-7v-2000mah-7-4wh/",
        "size_mm": (86.0, 30.0, 7.4),
        "continuous_a": None, "max_discharge_a": 5.0,
        "ntc": "10k", "pcm": True,
        "connector": "Molex 43645-0300", "connector_continuous_a": None,
        "lead_continuous_a": None,
    },
    "PR-CU-R512-22AWG": {
        "source": "https://www.batteryspace.com/custom-polymer-li-ion-battery-3-7v-2000mah-7-4-wh-4a-rate-with-10k-thermistor.aspx",
        "size_mm": (68.0, 50.0, 7.0),
        "continuous_a": None, "max_discharge_a": 4.0,
        "ntc": "10k", "pcm": True,
        "connector": "open ends CU-J484", "connector_continuous_a": None,
        "lead_continuous_a": 4.0,
        "terminal_roles": (("red", "positive"), ("black", "negative_ntc_return"),
                           ("white", "ntc")),
    },
    "PR-CU-R512-JST-SHR": {
        "source": "https://www.batteryspace.com/custom-polymer-li-ion-battery-3-7v-2000mah-7-4-wh-4a-rate-with-10k-thermistor.aspx",
        "size_mm": (68.0, 50.0, 7.0),
        "continuous_a": None, "max_discharge_a": 4.0,
        "ntc": "10k", "pcm": True,
        "connector": "JST SHR-03V-S 30AWG", "connector_continuous_a": 0.86,
        "lead_continuous_a": 0.86,
        "terminal_roles": (("pin_1", "negative"), ("pin_2", "ntc"),
                           ("pin_3", "positive")),
    },
    "NX-MGL00850-1S2P": {
        "source": "https://www.allbatteries.co.uk/li-ion-battery-2x-18650-1s2p-st1-3-6v-6-7ah-22awg-ntc-10k-mgl00850.html",
        "size_mm": (68.9, 37.4, 19.3),
        "continuous_a": 3.4, "max_discharge_a": 3.4,
        "ntc": "10k", "pcm": True,
        "connector": "22AWG 100mm lead; exact terminal and polarity unknown",
        "connector_continuous_a": None, "lead_continuous_a": None,
    },
    "VARTA-VAR56653502013": {
        "source": "https://my.avnet.com/wcm/connect/ccae6ad7-8e6a-4cc7-a362-0c6336823708/AvA-Standard-Batteries-EN-Brochure.pdf",
        "size_mm": (70.0, 38.0, 21.0),
        "continuous_a": 2.5, "max_discharge_a": 2.5,
        "ntc": "10k", "pcm": True,
        "connector": "Molex 5264-0300 with 5263-PBT terminals / 22AWG",
        "connector_continuous_a": None, "lead_continuous_a": None,
    },
    "LITECH-LP1S2P2A2AL005": {
        "source": "https://litechpower.com/product/litech-power-1s2p-3-7v-5-2ah-battery-pack-lp1s2p2a2al005/",
        "size_mm": (66.0, 39.0, 20.0),
        "continuous_a": 2.0, "max_discharge_a": 3.0,
        "ntc": "10k", "pcm": True,
        "connector": "20AWG open ends, terminal not chosen",
        "connector_continuous_a": None, "lead_continuous_a": None,
    },
    "BATTERYSPACE-CU-JAS427": {
        "source": "https://www.batteryspace.com/polymer-li-ion-battery-pack-3-7v-3000mah-11-1wh-5a-rate.aspx",
        "size_mm": (66.5, 37.5, 14.5),  # +1.5mm maker dimensional tolerance
        "continuous_a": None, "max_discharge_a": 5.0,
        "ntc": "10k", "pcm": True,
        "connector": "6in 22AWG open ends, terminal not chosen",
        "connector_continuous_a": None, "lead_continuous_a": None,
    },
    "THOR-18650-1S2P-5200": {
        "source": "https://thorbattery.com/product/thor-18650-1s2p-5200/",
        "size_mm": (65.0, 37.0, 18.4),  # BARE PACK; unfinished PCM adds volume
        # Vendor explicitly limits 10.4 A to the cells; the PCM sets the pack ceiling.
        "continuous_a": None, "max_discharge_a": None,
        "cell_level_max_discharge_a": 10.4,
        "ntc": "optional", "pcm": True,
        "connector": "Default PH2.0; optional NTC and PCM current are unspecified",
        "connector_continuous_a": None, "lead_continuous_a": None,
    },
    "PR-CU-R512-Molex-26AWG": {
        "source": "https://www.batteryspace.com/custom-polymer-li-ion-battery-3-7v-2000mah-7-4-wh-4a-rate-with-10k-thermistor.aspx",
        "size_mm": (68.0, 50.0, 7.0),
        "continuous_a": None, "max_discharge_a": 4.0,
        "ntc": "10k", "pcm": True,
        "connector": "Molex 51021-0300 26AWG", "connector_continuous_a": 2.2,
        "lead_continuous_a": 2.2,
        "terminal_roles": (("pin_1", "positive"), ("pin_2", "ntc"),
                           ("pin_3", "negative_ntc_return")),
    },
}


def catalog() -> dict:
    return {key: dict(value) for key, value in _PACKS.items()}


_TRAY_CAD = Path(__file__).resolve().parents[2] / (
    "docs/cad/remixes/remaining_fit_gauges.scad"
)


def cad_tray_mm(source: Path = _TRAY_CAD) -> tuple[float, float, float]:
    """Read the one current CAD candidate cavity, never a stale CLI default."""
    text = source.read_text(encoding="utf-8")
    sizes = []
    for axis in ("l", "w", "h"):
        matches = re.findall(
            rf"^power_{axis}\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;",
            text, flags=re.MULTILINE,
        )
        if len(matches) != 1:
            raise ValueError(f"Missing or ambiguous power_{axis} CAD dimension")
        sizes.append(float(matches[0]))
    if not all(0 < dimension < 1000 for dimension in sizes):
        raise ValueError("CAD battery cavity dimensions are invalid")
    return tuple(sizes)


def evaluate(model: str, demand: dict, *, tray_mm=None,
             wire_relief_mm=8.0, clearance_mm=1.0) -> dict:
    if model not in _PACKS:
        raise ValueError("Unknown sourced protected pack model")
    src = _PACKS[model]
    # The existing demand source is the single owner of boost input sizing.
    if not isinstance(demand, dict) or not all(
        isinstance(demand.get(key), (float, int)) and
        not isinstance(demand.get(key), bool) and
        demand[key] > 0 and demand[key] < 100
        for key in ("minimum_rated_cell_and_boost_input_a",
                    "minimum_continuous_cell_input_a")
    ):
        raise ValueError("No valid measured-load power preflight")
    # Both inputs derive from the same peak/continuous 5V load and
    # low-cell boost calculation. A sustained requirement larger than its
    # peak is contradictory, not an alternative battery recommendation.
    if demand["minimum_continuous_cell_input_a"] > demand[
        "minimum_rated_cell_and_boost_input_a"
    ]:
        raise ValueError("Continuous battery demand exceeds peak demand")
    a, b, h = src["size_mm"]
    if tray_mm is None:
        tray_mm = cad_tray_mm()
    lt, wt, ht = tray_mm
    dims = (lt, wt, ht, wire_relief_mm, clearance_mm)
    if not all(type(v) in (int, float) and 0 <= v < 1000 for v in dims):
        raise ValueError("Invalid physical tray or clearance")
    if min(lt, wt, ht) <= 0:
        raise ValueError("Empty battery envelope")
    fit = (h + 2 * clearance_mm <= ht and
           ((a + wire_relief_mm + 2 * clearance_mm <= lt and
             b + 2 * clearance_mm <= wt) or
            (b + wire_relief_mm + 2 * clearance_mm <= lt and
             a + 2 * clearance_mm <= wt)))
    # THOR includes a configurable PCM and optional NTC, but publishes only
    # bare-pack dimensions. The final protector, wiring and connector add volume.
    if model == "THOR-18650-1S2P-5200":
        fit = None
    peak = demand["minimum_rated_cell_and_boost_input_a"]
    cont = demand["minimum_continuous_cell_input_a"]
    # "Maximum discharge current" is not a published continuous rating.
    # All listed manufacturers require a confirmed thermal duty rating for
    # the actual terminal configuration before sustained robot operation.
    pack_max = src["max_discharge_a"]
    cell_ceiling = src.get("cell_level_max_discharge_a")
    if pack_max is not None:
        peak_ok = pack_max >= peak
    else:
        # A cell-level ceiling can rule a pack out, but cannot establish
        # that an unspecified protection circuit supports the required load.
        peak_ok = False if cell_ceiling is not None and cell_ceiling < peak else None
    pack_ok = (None if src["continuous_a"] is None else
               src["continuous_a"] >= cont and peak_ok)
    # A proven cell is still unsafe with a narrower connector/lead assembly.
    conn = src["connector_continuous_a"]
    lead = src["lead_continuous_a"]
    harness_ok = (conn is not None and lead is not None and
                  conn >= peak and lead >= peak)
    reasons = []
    if fit is None:
        reasons.append("full_protected_pack_dimensions_unknown")
    elif not fit:
        reasons.append("protected_pack_does_not_fit_existing_cavity")
    if pack_max is None:
        reasons.append("manufacturer_assembled_pack_peak_discharge_rating_missing")
        if peak_ok is False:
            reasons.append("cell_level_discharge_below_peak_budget")
    elif peak_ok is False:
        reasons.append("pack_max_discharge_below_peak_budget")
    if pack_ok is None:
        reasons.append("manufacturer_continuous_discharge_rating_missing")
    elif not pack_ok:
        reasons.append("pack_current_rating_below_load_budget")
    if conn is None or lead is None:
        reasons.append("exact_connector_or_lead_ampacity_missing")
    if any(rating is not None and rating < peak for rating in (conn, lead)):
        reasons.append("exact_connector_or_lead_ampacity_insufficient")
    # These are published assignments, not continuity or polarity measurements.
    terminal_roles = src.get("terminal_roles")
    if terminal_roles is None:
        reasons.append("manufacturer_terminal_pinout_missing")
    reasons.append("physical_harness_wiring_not_verified")
    if src["ntc"] != "10k":
        reasons.append("pack_ntc_10k_not_fitted_in_exact_variant")
    if model == "THOR-18650-1S2P-5200":
        reasons.append("bare_cell_envelope_not_complete_protected_pack")
        reasons.append("pcm_current_limit_and_connector_configuration_unselected")
    reasons += ["charger_ntc_circuit_not_qualified",
                "physical_power_and_fit_trials_not_executed"]
    return {
        "model": model, "vendor_source": src["source"],
        "protected": src["pcm"], "ntc": src["ntc"],
        "connector_variant": src["connector"],
        "published_terminal_roles": dict(terminal_roles) if terminal_roles else None,
        "physical_harness_wiring_verified": False,
        "assembled_pack_mm": None if fit is None else src["size_mm"],
        "bare_pack_mm": src["size_mm"] if fit is None else None,
        "cell_level_max_discharge_a": cell_ceiling,
        "pack_fits_current_tray_on_paper": fit,
        "pack_peak_within_published_max_on_paper": peak_ok,
        "pack_current_enough_on_paper": pack_ok,
        "harness_ampacity_enough_on_paper": harness_ok,
        "complete_power_path_safe_to_buy": False,
        "blocking_reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peak-5v-a", required=True, type=float)
    parser.add_argument("--continuous-5v-a", required=True, type=float)
    parser.add_argument("--tray-length-mm", type=float)
    parser.add_argument("--tray-width-mm", type=float)
    parser.add_argument("--tray-height-mm", type=float)
    args = parser.parse_args()
    sizing = runpy.run_path(
        str(Path(__file__).with_name("power_preflight.py")))
    demand = sizing["size_5v_supply"](
        args.peak_5v_a, args.continuous_5v_a)
    cad = cad_tray_mm()
    tray = tuple(
        override if override is not None else baseline
        for override, baseline in zip(
            (args.tray_length_mm, args.tray_width_mm, args.tray_height_mm),
            cad, strict=True,
        )
    )
    print(json.dumps({
        "load_source": "hypothetical until operator measured",
        "sizing": demand,
        "candidates": [evaluate(name, demand, tray_mm=tray)
                       for name in _PACKS],
    }, indent=2))


if __name__ == "__main__":
    main()
