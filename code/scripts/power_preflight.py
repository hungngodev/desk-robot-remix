"""Conservative full one-pet 1S battery and 5V boost sizing from measured load.

This tool does not recommend a protected cell or charge circuit on speculation.
Use measured simultaneous motor, servo, camera, WiFi and audio load readings.
"""
from __future__ import annotations

import argparse
import json
import math
from decimal import ROUND_CEILING, Decimal


def _finite_number(value: object) -> bool:
    """Reject invalid and unrepresentably large telemetry without overflow."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def size_5v_supply(
    measured_peak_5v_a: float,
    measured_continuous_5v_a: float,
    *,
    cell_low_v: float = 3.0,
    measured_boost_efficiency: float = 0.85,
    margin: float = 1.3,
    boost_max_input_a: float | None = None,
    boost_continuous_input_a: float | None = None,
    boost_continuous_output_a: float | None = None,
    protected_cell_continuous_a: float | None = None,
) -> dict:
    values = [
        measured_peak_5v_a, measured_continuous_5v_a,
        cell_low_v, measured_boost_efficiency, margin,
    ]
    if any(not _finite_number(v) for v in values):
        raise ValueError("All current, efficiency and voltage inputs must be finite")
    if not 0 < measured_continuous_5v_a <= measured_peak_5v_a <= 20:
        raise ValueError("Peak/continuous load missing or invalid")
    if not 2.5 <= cell_low_v <= 4.1:
        raise ValueError("Single-cell low voltage must be measured/qualified")
    if not 0.5 <= measured_boost_efficiency <= 0.99 or not 1 <= margin <= 2:
        raise ValueError("Qualified boost efficiency and current margin required")
    ratings = (boost_max_input_a, boost_continuous_input_a, boost_continuous_output_a, protected_cell_continuous_a)
    for rating in ratings:
        if rating is not None and (not _finite_number(rating) or rating <= 0):
            raise ValueError("Rated board current must be positive and finite")
    if (boost_max_input_a is not None and boost_continuous_input_a is not None
            and boost_continuous_input_a > boost_max_input_a):
        raise ValueError("Continuous boost input rating exceeds maximum input rating")
    # Decimal input values avoid floating point false equality at a rating
    # boundary. Report required amperes rounded UP, never below actual need.
    required_5v_peak = Decimal(str(measured_peak_5v_a)) * Decimal(str(margin))
    required_cell_peak = (Decimal(5) * required_5v_peak
                          / (Decimal(str(cell_low_v))
                             * Decimal(str(measured_boost_efficiency))))
    required_5v_cont = Decimal(str(measured_continuous_5v_a)) * Decimal(str(margin))
    required_cell_cont = (Decimal(5) * required_5v_cont
                          / (Decimal(str(cell_low_v))
                             * Decimal(str(measured_boost_efficiency))))
    milliamp = Decimal("0.001")
    boosted_peak = float(required_5v_peak.quantize(milliamp, rounding=ROUND_CEILING))
    cell_peak = float(required_cell_peak.quantize(milliamp, rounding=ROUND_CEILING))
    boosted_cont = float(required_5v_cont.quantize(milliamp, rounding=ROUND_CEILING))
    cell_cont = float(required_cell_cont.quantize(milliamp, rounding=ROUND_CEILING))
    requirements = {
        "measured_peak_5v_a": measured_peak_5v_a,
        "measured_continuous_5v_a": measured_continuous_5v_a,
        "minimum_rated_5v_output_a": boosted_peak,
        "minimum_rated_cell_and_boost_input_a": cell_peak,
        "minimum_rated_continuous_5v_a": boosted_cont,
        "minimum_continuous_cell_input_a": cell_cont,
        "minimum_protected_cell_discharge_a": cell_peak,
        "charger_and_load_sharing_verified": False,
        "thermal_and_brownout_verified": False,
        "physical_load_verified": False,
    }
    if all(rating is not None for rating in ratings):
        requirements["candidate_electrically_sufficient_on_paper"] = (
            Decimal(str(boost_max_input_a)) >= Decimal(str(cell_peak))
            and Decimal(str(boost_continuous_input_a)) >= Decimal(str(cell_cont))
            and Decimal(str(boost_continuous_output_a)) >= Decimal(str(boosted_peak))
            and Decimal(str(protected_cell_continuous_a)) >= Decimal(str(cell_peak))
        )
        requirements["candidate_physically_qualified"] = False
    else:
        requirements["candidate_electrically_sufficient_on_paper"] = None
        requirements["candidate_physically_qualified"] = False
    return requirements



def screen_protected_pack(
    supply: dict,
    *,
    pack_length_mm: float,
    pack_width_mm: float,
    pack_thickness_mm: float,
    tray_length_mm: float,
    tray_width_mm: float,
    tray_height_mm: float,
    wire_relief_mm: float = 8.0,
    side_clearance_mm: float = 1.0,
    rated_peak_discharge_a: float | None = None,
    rated_continuous_discharge_a: float | None = None,
    pcm_overcurrent_trip_a: float | None = None,
    connector_continuous_a: float | None = None,
    wire_and_crimp_continuous_a: float | None = None,
) -> dict:
    """Screen a REAL assembled protected pack against the selected tray.

    Reuse the pre-existing size_5v_supply electrical demand: do not confuse
    nominal mAh, advertised '3C' pulse, or a charger current with continuous
    cell discharge and its protection circuit trip point. The dimensions are
    the entire protected, wired pack, not an unwrapped bare cell. Actual
    bending, restraint, insulation, connector and NTC tests remain required.
    """
    if not isinstance(supply, dict) or not all(
        _finite_number(supply.get(name)) and supply[name] > 0
        for name in ("minimum_rated_cell_and_boost_input_a",
                     "minimum_continuous_cell_input_a")
    ):
        raise ValueError("Provide measured-load 1S sizing report first")
    if (supply["minimum_continuous_cell_input_a"] >
            supply["minimum_rated_cell_and_boost_input_a"]):
        raise ValueError("Continuous cell demand cannot exceed peak cell demand")
    dimensions = (pack_length_mm, pack_width_mm, pack_thickness_mm,
                  tray_length_mm, tray_width_mm, tray_height_mm,
                  wire_relief_mm, side_clearance_mm)
    if (any(not _finite_number(x) for x in dimensions)
            or any(x <= 0 for x in dimensions[:6])
            or wire_relief_mm < 0 or side_clearance_mm < 0):
        raise ValueError("Actual positive pack/tray dimensions and clearance required")
    if any(x > 1000 for x in dimensions[:6]):
        raise ValueError("Unrepresentable physical pack/tray envelope")
    ratings = (rated_peak_discharge_a, rated_continuous_discharge_a,
               pcm_overcurrent_trip_a)
    interconnect_ratings = (connector_continuous_a, wire_and_crimp_continuous_a)
    if any(r is not None and (not _finite_number(r) or r <= 0)
           for r in interconnect_ratings):
        raise ValueError("Actual connector and wire/crimp current rating must be positive")
    if any(r is not None and (not _finite_number(r) or r <= 0) for r in ratings):
        raise ValueError("Pack discharge and PCM ratings must be positive real amperes")
    if all(r is not None for r in ratings):
        if (rated_continuous_discharge_a > rated_peak_discharge_a
                or pcm_overcurrent_trip_a < rated_peak_discharge_a):
            raise ValueError("Contradictory protected pack peak, continuous or PCM ratings")
    fits_flat = (
        pack_thickness_mm + 2 * side_clearance_mm <= tray_height_mm
        and any(
            length + wire_relief_mm + 2 * side_clearance_mm <= tray_length_mm
            and width + 2 * side_clearance_mm <= tray_width_mm
            for length, width in (
                (pack_length_mm, pack_width_mm),
                (pack_width_mm, pack_length_mm),
            )
        )
    )
    ratings_complete = all(v is not None for v in ratings)
    peak = Decimal(str(supply["minimum_rated_cell_and_boost_input_a"]))
    continuous = Decimal(str(supply["minimum_continuous_cell_input_a"]))
    if any(
        rating is not None and Decimal(str(rating)) < required
        for rating, required in zip(ratings, (peak, continuous, peak), strict=True)
    ):
        current_ok = False
    else:
        current_ok = True if ratings_complete else None
    # A 4A cell can ship with a 0.86A JST harness. Current through the
    # terminated connector and wires is NOT the cell's printed 4A rating.
    # Without a separately published pulse rating, conservatively compare
    # even short motor stalls to the connector's continuous ampacity.
    interconnect_complete = all(v is not None for v in interconnect_ratings)
    if any(v is not None and Decimal(str(v)) < peak for v in interconnect_ratings):
        interconnect_ok = False
    else:
        interconnect_ok = True if interconnect_complete else None
    # Unlike the legacy pack-only indication, this field covers the complete
    # exact wired battery assembly and cannot pass without both ratings.
    # If any known hard bound fails, the answer is definitively NO even
    # when another supplier specification is missing. Otherwise an unknown
    # connector MUST remain unknown, never a misleading qualified YES.
    complete_harness_usable = (
        False if not fits_flat or current_ok is False or interconnect_ok is False
        else True if ratings_complete and interconnect_complete else None)
    return {
        "assembled_pack_fits_tray_on_paper": fits_flat,
        "current_ratings_complete": ratings_complete,
        "current_sufficient_on_paper": current_ok,
        "candidate_usable_on_paper": complete_harness_usable,
        "pack_only_usable_on_paper": (
            False if not fits_flat else current_ok
        ),
        "connector_and_wire_ratings_complete": interconnect_complete,
        "connector_and_wire_current_sufficient_on_paper": interconnect_ok,
        "minimum_cell_peak_a": supply["minimum_rated_cell_and_boost_input_a"],
        "minimum_cell_continuous_a": supply["minimum_continuous_cell_input_a"],
        "actual_pack_pcm_and_ntc_test_verified": False,
        "charger_load_sharing_and_thermal_verified": False,
        "printed_assembly_and_wire_relief_verified": False,
        "candidate_physically_qualified": False,
    }


def screen_bq2407x_output_path(
    charger_variant: str,
    *, regulator_min_input_v: float, regulator_max_input_v: float,
    regulator_topology: str = "boost_only",
    bypasses_5v_regulator: bool = False,
) -> dict:
    """Require a converter input rating that covers both docked and 1S power.

    Manufacturer Rev N: BQ24074 OUT=4.3..4.5V, BQ24075 OUT=5.4..5.6V
    when the input is sufficient for voltage regulation. On battery supply
    OUT follows the Li-ion cell, with no guaranteed fixed 5V rail. The
    conservative 3.0V lower bound is a design target, not a tested UVLO.
    A passing range check NEVER qualifies a real charger, pack or boost.
    """
    if charger_variant not in ("BQ24074", "BQ24075"):
        raise ValueError("Use a source-reviewed BQ24074 or BQ24075 variant")
    if (not _finite_number(regulator_min_input_v)
            or not _finite_number(regulator_max_input_v)
            or regulator_min_input_v <= 0
            or regulator_min_input_v >= regulator_max_input_v):
        raise ValueError("Regulator input voltage ratings must be real and ordered")
    if type(bypasses_5v_regulator) is not bool:
        raise ValueError("Direct 5V rail bypass must be explicit")
    if regulator_topology not in ("boost_only", "buck_boost"):
        raise ValueError("Regulator topology must be verified boost_only or buck_boost")
    docked_output_max_v = 4.5 if charger_variant == "BQ24074" else 5.6
    # A step-up-only converter does not regulate downward from a possible
    # 5.6 V BQ24075 SYS node to a 5.0 V rail. A claimed wide VIN rating
    # alone is NOT proof that its output remains fixed at five volts.
    topology_suitable = (charger_variant == "BQ24074" or
                         regulator_topology == "buck_boost")
    return {
        "charger_ic": charger_variant,
        "docked_output_max_v": docked_output_max_v,
        "conservative_low_cell_design_v": 3.0,
        "regulator_topology": regulator_topology,
        "topology_supports_regulating_5v_both_modes": topology_suitable,
        "regulator_covers_charger_output_on_paper": (
            not bypasses_5v_regulator and topology_suitable
            and regulator_min_input_v <= 3.0
            and regulator_max_input_v >= docked_output_max_v
        ),
        "fixed_5v_direct_output_prohibited": True,
        "real_docked_voltage_measured": False,
        "charger_and_5v_rail_physically_qualified": False,
    }


def assess_docked_load(
    measured_idle_5v_a: float,
    requested_cell_charge_a: float,
    *,
    measured_sys_v: float,
    measured_boost_efficiency: float,
    charger_input_limit_a: float | None = None,
    charger_board_thermal_input_a: float | None = None,
    dock_adapter_continuous_a: float | None = None,
    rated_5v_boost_continuous_a: float | None = None,
    protected_pack_max_charge_a: float | None = None,
    reserve: float = 1.2,
    motors_confirmed_disarmed: bool = False,
    charger_variant: str | None = None,
) -> dict:
    """Conservatively bound simultaneous idle system and 1S charge currents.

    TI BQ24074 OUT is 4.3..4.5V docked; BQ24075 can be 5.4..5.6V.
    Neither is a fixed 5V motor rail. The charger 1.5A input rating is
    NOT a 1.5A boosted system plus an
    independent 1.5A charge budget. A separate boost supplies 5V.
    This is a conservative input-current arithmetic gate, not a battery
    charge measurement, thermal/NTC proof or enable signal.
    """
    measured = (measured_idle_5v_a, requested_cell_charge_a, measured_sys_v,
                measured_boost_efficiency, reserve)
    if any(not _finite_number(x) for x in measured):
        raise ValueError("Actual docked loads and conversion measurements required")
    if charger_variant not in ("BQ24074", "BQ24075"):
        raise ValueError("Explicit BQ24074 or BQ24075 charger variant required")
    max_out_v = 4.5 if charger_variant == "BQ24074" else 5.6
    if (not 0 < measured_idle_5v_a <= 20
            or not 0 < requested_cell_charge_a <= 5
            or not 3.0 <= measured_sys_v <= max_out_v
            or not 0.5 <= measured_boost_efficiency <= 0.99
            or not 1 <= reserve <= 2):
        raise ValueError("Invalid docked load, cell, SYS or reserve measurement")
    if type(motors_confirmed_disarmed) is not bool:
        raise ValueError("Motor disarm state must be an explicit physical boolean")
    # BQ24074 and BQ24075 do not support >1.5 A input or cell
    # charging. Keep this bound in the reusable dock screen too, not
    # only in the whole-stack wrapper, where direct callers can bypass it.
    if requested_cell_charge_a > 1.5:
        raise ValueError("BQ2407x cell charge request cannot exceed 1.5A")
    if charger_input_limit_a is not None:
        # Reject malformed direct-API inputs before the numeric limit check.
        if not _finite_number(charger_input_limit_a):
            raise ValueError("BQ2407x charger input limit must be finite amperes")
        if charger_input_limit_a > 1.5:
            raise ValueError("BQ2407x charger input limit cannot exceed 1.5A")
    ratings = (charger_input_limit_a, charger_board_thermal_input_a,
               dock_adapter_continuous_a, rated_5v_boost_continuous_a,
               protected_pack_max_charge_a)
    if any(v is not None and (not _finite_number(v) or v <= 0)
           for v in ratings):
        raise ValueError("Positive real component ratings are required")
    def decimal(x):
        return Decimal(str(x))
    boost_input = (Decimal("5") * decimal(measured_idle_5v_a)
                   / (decimal(measured_sys_v)
                      * decimal(measured_boost_efficiency)))
    # Do not use a status LED as evidence that the battery has net charge.
    # With a linear 1S charger, conservatively budget separate pack charge
    # current plus measured system draw on the dock input.
    required_dock_input = (
        boost_input + decimal(requested_cell_charge_a)) * decimal(reserve)
    required_5v = decimal(measured_idle_5v_a) * decimal(reserve)
    required_pack = decimal(requested_cell_charge_a) * decimal(reserve)
    milliamp = Decimal("0.001")

    def ceiling(value: Decimal) -> float:
        return float(value.quantize(milliamp, rounding=ROUND_CEILING))

    total = ceiling(required_dock_input)
    five_v = ceiling(required_5v)
    charge = ceiling(required_pack)
    on_paper = None
    if all(v is not None for v in ratings):
        on_paper = (
            motors_confirmed_disarmed
            and all(decimal(v) >= decimal(total)
                    for v in ratings[:3])
            and decimal(rated_5v_boost_continuous_a) >= decimal(five_v)
            and decimal(protected_pack_max_charge_a) >= decimal(charge)
        )
    return {
        "charger_variant": charger_variant,
        "charger_variant_max_docked_out_v": max_out_v,
        "fixed_5v_rail_requires_separate_converter": True,
        "measured_idle_5v_a": measured_idle_5v_a,
        "requested_cell_charge_a": requested_cell_charge_a,
        "required_sys_to_boost_input_a": ceiling(boost_input * decimal(reserve)),
        "minimum_sustained_dock_input_a": total,
        "minimum_sustained_5v_output_a": five_v,
        "minimum_protected_pack_charge_rating_a": charge,
        "motors_confirmed_disarmed": motors_confirmed_disarmed,
        "candidate_docked_load_on_paper": on_paper,
        "signed_battery_charge_current_measured": False,
        "charger_ntc_and_thermal_verified": False,
        "contact_protection_and_reverse_polarity_verified": False,
        "charger_and_load_sharing_verified": False,
        "candidate_physically_qualified": False,
    }

def screen_one_cell_power_stack(
    *,
    active_peak_5v_a: float,
    active_sustained_5v_a: float,
    dock_idle_5v_a: float,
    charge_request_a: float,
    pack_mm: tuple[float, float, float],
    tray_mm: tuple[float, float, float],
    pack_peak_a: float | None,
    pack_sustained_a: float | None,
    pcm_trip_a: float | None,
    connector_a: float | None,
    wire_crimp_a: float | None,
    boost_input_max_a: float | None,
    boost_input_continuous_a: float | None,
    boost_output_at_3v_continuous_a: float | None,
    boost_regulator_min_input_v: float,
    boost_regulator_max_input_v: float,
    regulator_topology: str,
    charger_input_limit_a: float | None,
    charger_thermal_input_a: float | None,
    dock_adapter_continuous_a: float | None,
    pack_charge_max_a: float | None,
    docked_sys_v: float,
    charge_temperature_sensor_connected: bool,
    charger_ts_fixed_resistor_removed: bool,
    dock_motors_disarmed: bool,
    charger_variant: str | None = None,
    boost_efficiency_low_cell: float = 0.85,
    boost_efficiency_docked: float = 0.85,
) -> dict:
    """Join existing 1S equations into ONE real purchase architecture screen.

    Do not misuse a 3A-at-5V regulator label as 3A-at-3V proof; require
    derated data at the worst battery voltage. Source references include TI
    BQ2407x Rev N and exact candidate regulator datasheets and load graphs.
    A returned paper pass is NEVER PCB, thermal, protection or dock approval.
    """
    if any(type(v) is not bool for v in (
            charge_temperature_sensor_connected,
            charger_ts_fixed_resistor_removed,
            dock_motors_disarmed)):
        raise ValueError("Real TS and motor-disarm modes must be explicit booleans")
    if not isinstance(pack_mm, (tuple, list)) or len(pack_mm) != 3 or (
            not isinstance(tray_mm, (tuple, list)) or len(tray_mm) != 3):
        raise ValueError("Require exact assembled pack and tray 3D envelopes")
    if charger_input_limit_a is not None:
        # Use the same type/finite guard as the standalone dock screen.
        if not _finite_number(charger_input_limit_a):
            raise ValueError("BQ2407x dock charger input limit must be finite amperes")
        if charger_input_limit_a > 1.5:
            raise ValueError("BQ2407x maximum dock charger input is not above 1.5A")
    # Source of truth: do not silently add a new third power-supply formula.
    undocked = size_5v_supply(
        active_peak_5v_a, active_sustained_5v_a,
        cell_low_v=3.0, measured_boost_efficiency=boost_efficiency_low_cell,
        boost_max_input_a=boost_input_max_a,
        boost_continuous_input_a=boost_input_continuous_a,
        boost_continuous_output_a=boost_output_at_3v_continuous_a,
        protected_cell_continuous_a=pack_sustained_a)
    protected = screen_protected_pack(
        undocked,
        pack_length_mm=pack_mm[0], pack_width_mm=pack_mm[1],
        pack_thickness_mm=pack_mm[2],
        tray_length_mm=tray_mm[0], tray_width_mm=tray_mm[1],
        tray_height_mm=tray_mm[2],
        rated_peak_discharge_a=pack_peak_a,
        rated_continuous_discharge_a=pack_sustained_a,
        pcm_overcurrent_trip_a=pcm_trip_a,
        connector_continuous_a=connector_a,
        wire_and_crimp_continuous_a=wire_crimp_a)
    vpath = screen_bq2407x_output_path(
        charger_variant,
        regulator_min_input_v=boost_regulator_min_input_v,
        regulator_max_input_v=boost_regulator_max_input_v,
        regulator_topology=regulator_topology)
    docked = assess_docked_load(
        dock_idle_5v_a, charge_request_a,
        measured_sys_v=docked_sys_v,
        measured_boost_efficiency=boost_efficiency_docked,
        charger_input_limit_a=charger_input_limit_a,
        charger_board_thermal_input_a=charger_thermal_input_a,
        dock_adapter_continuous_a=dock_adapter_continuous_a,
        rated_5v_boost_continuous_a=boost_output_at_3v_continuous_a,
        protected_pack_max_charge_a=pack_charge_max_a,
        motors_confirmed_disarmed=dock_motors_disarmed,
        charger_variant=charger_variant)
    gates = {
        "charger_out_to_regulated_5v_covers_3v_cell_and_dock": (
            vpath["regulator_covers_charger_output_on_paper"]),
        "regulator_current_and_pack_low_cell_budget": (
            undocked["candidate_electrically_sufficient_on_paper"] is True),
        "whole_protected_cell_pcm_cable_and_tray": (
            protected["candidate_usable_on_paper"] is True),
        "docked_idle_plus_cell_charge_in_same_1_5a_budget": (
            docked["candidate_docked_load_on_paper"] is True),
        "charger_ts_is_connected_to_actual_pack_ntc": (
            charge_temperature_sensor_connected and
            charger_ts_fixed_resistor_removed),
        "physical_motor_commands_inhibited_on_dock": dock_motors_disarmed,
    }
    return {
        "source_of_equations": "existing power_preflight.py",
        "charger_variant": charger_variant,
        "minimum_5v_peak_a_including_margin": (
            undocked["minimum_rated_5v_output_a"]),
        "minimum_1s_peak_a_including_margin": (
            undocked["minimum_rated_cell_and_boost_input_a"]),
        "manufacturer_derated_at_3v_boost_amperes_supplied": (
            boost_output_at_3v_continuous_a),
        "checks": gates,
        "all_power_stages_compatible_on_paper": all(gates.values()),
        "all_power_stages_physically_verified": False,
        "qualified_1s_dock_safe_to_buy": False,
        "undocked": undocked,
        "battery_and_harness": protected,
        "voltage_path": vpath,
        "docked": docked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peak-5v-a", type=float)
    parser.add_argument("--continuous-5v-a", type=float)
    # None distinguishes an explicitly supplied undocked value from a
    # default, so dock mode cannot silently ignore even a repeated default.
    parser.add_argument("--low-cell-v", type=float)
    parser.add_argument("--measured-efficiency", type=float)
    parser.add_argument("--margin", type=float,
                        help="Conservative current reserve multiplier (1.0 to 2.0)")
    parser.add_argument("--boost-max-input-a", type=float)
    parser.add_argument("--boost-continuous-input-a", type=float)
    parser.add_argument("--boost-continuous-output-a", type=float)
    parser.add_argument("--protected-cell-continuous-a", type=float)
    # Use the SAME existing source owner to size real low-motion dock loads.
    # No default numeric input is represented as a measured charger rating.
    parser.add_argument("--dock-idle-5v-a", type=float)
    parser.add_argument("--dock-requested-charge-a", type=float)
    parser.add_argument("--dock-sys-v", type=float)
    # The source register considers BQ24075 while older comparison docs use
    # BQ24074. These have different docked OUT voltages. A silent default
    # could screen the wrong regulator topology, so require an explicit
    # physically inspected variant for every dock analysis.
    parser.add_argument("--dock-charger-variant", choices=("BQ24074", "BQ24075"))
    parser.add_argument("--dock-regulator-topology",
                        choices=("boost_only", "buck_boost"))
    parser.add_argument("--dock-regulator-min-input-v", type=float)
    parser.add_argument("--dock-regulator-max-input-v", type=float)
    parser.add_argument("--dock-boost-efficiency", type=float)
    parser.add_argument("--dock-charger-input-limit-a", type=float)
    parser.add_argument("--dock-board-thermal-input-a", type=float)
    parser.add_argument("--dock-adapter-continuous-a", type=float)
    parser.add_argument("--dock-boost-5v-continuous-a", type=float)
    parser.add_argument("--dock-pack-charge-max-a", type=float)
    parser.add_argument("--dock-motors-disarmed", action="store_true")
    # Optional assembled protected-pack screening, tied to the existing 1S
    # measured-load supply report. A seller photograph or nominal mAh is
    # never proof of wire clearance, NTC wiring or PCM trip behavior.
    parser.add_argument("--pack-length-mm", type=float)
    parser.add_argument("--pack-width-mm", type=float)
    parser.add_argument("--pack-thickness-mm", type=float)
    parser.add_argument("--tray-length-mm", type=float)
    parser.add_argument("--tray-width-mm", type=float)
    parser.add_argument("--tray-height-mm", type=float)
    parser.add_argument("--pack-wire-relief-mm", type=float)
    parser.add_argument("--pack-side-clearance-mm", type=float)
    parser.add_argument("--pack-peak-discharge-a", type=float)
    parser.add_argument("--pack-continuous-discharge-a", type=float)
    parser.add_argument("--pack-pcm-trip-a", type=float)
    parser.add_argument("--pack-connector-continuous-a", type=float,
                        help="Manufacturer current rating for the exact polarized plug and pins")
    parser.add_argument("--pack-wire-crimp-continuous-a", type=float,
                        help="Actual terminated leads and crimp current rating")
    args = parser.parse_args()
    pack_dimensions = (
        args.pack_length_mm, args.pack_width_mm, args.pack_thickness_mm,
        args.tray_length_mm, args.tray_width_mm, args.tray_height_mm,
    )
    pack_ratings = (
        args.pack_peak_discharge_a, args.pack_continuous_discharge_a,
        args.pack_pcm_trip_a,
        args.pack_connector_continuous_a,
        args.pack_wire_crimp_continuous_a,
    )
    # Explicit pack clearances request the pack screen too. Without all
    # geometry a standalone option must fail, never silently disappear.
    pack_requested = (
        any(x is not None for x in pack_dimensions + pack_ratings)
        or args.pack_wire_relief_mm is not None
        or args.pack_side_clearance_mm is not None
    )
    if pack_requested and any(x is None for x in pack_dimensions):
        parser.error("Pack mode requires all three assembled pack and tray dimensions")
    dock_inputs = (
        args.dock_idle_5v_a, args.dock_requested_charge_a, args.dock_sys_v,
        args.dock_boost_efficiency,
    )
    # Supplying a charger identity or rating is itself a request to screen
    # the dock. Never silently drop those flags into undocked battery sizing.
    dock_only_options = (
        args.dock_charger_variant, args.dock_regulator_topology,
        args.dock_regulator_min_input_v, args.dock_regulator_max_input_v,
        args.dock_charger_input_limit_a, args.dock_board_thermal_input_a,
        args.dock_adapter_continuous_a, args.dock_boost_5v_continuous_a,
        args.dock_pack_charge_max_a,
    )
    if (any(v is not None for v in dock_inputs + dock_only_options)
            or args.dock_motors_disarmed):
        if args.dock_charger_variant is None:
            parser.error("Dock mode requires the actual BQ24074 or BQ24075 charger variant")
        if any(v is None for v in dock_inputs):
            parser.error("Dock mode requires idle current, charge current, SYS voltage and efficiency")
        if (args.dock_regulator_topology is None
                or args.dock_regulator_min_input_v is None
                or args.dock_regulator_max_input_v is None):
            parser.error("Dock mode requires converter topology and actual input voltage ratings")
        if args.peak_5v_a is not None or args.continuous_5v_a is not None:
            parser.error("Use one mode: undocked peak load OR docked idle load")
        if any(value is not None for value in (
                args.low_cell_v, args.measured_efficiency, args.margin,
                args.boost_max_input_a, args.boost_continuous_input_a,
                args.boost_continuous_output_a,
                args.protected_cell_continuous_a)):
            parser.error("Undocked-only power sizing flags cannot be used in dock mode")
        if pack_requested:
            parser.error("Pack geometry screening is for undocked load mode only")
        result = assess_docked_load(
            args.dock_idle_5v_a, args.dock_requested_charge_a,
            measured_sys_v=args.dock_sys_v,
            measured_boost_efficiency=args.dock_boost_efficiency,
            charger_input_limit_a=args.dock_charger_input_limit_a,
            charger_board_thermal_input_a=args.dock_board_thermal_input_a,
            dock_adapter_continuous_a=args.dock_adapter_continuous_a,
            rated_5v_boost_continuous_a=args.dock_boost_5v_continuous_a,
            protected_pack_max_charge_a=args.dock_pack_charge_max_a,
            motors_confirmed_disarmed=args.dock_motors_disarmed,
            charger_variant=args.dock_charger_variant,
        )
        voltage_path = screen_bq2407x_output_path(
            args.dock_charger_variant,
            regulator_min_input_v=args.dock_regulator_min_input_v,
            regulator_max_input_v=args.dock_regulator_max_input_v,
            regulator_topology=args.dock_regulator_topology,
        )
        result["voltage_path"] = voltage_path
        if not voltage_path["regulator_covers_charger_output_on_paper"]:
            # The current limit arithmetic alone must not claim paper
            # compatibility while a boost-only converter faces a BQ24075
            # 5.6V OUT node, or the regulator VIN envelope is inadequate.
            result["candidate_docked_load_on_paper"] = False
    else:
        if args.peak_5v_a is None or args.continuous_5v_a is None:
            parser.error("Undocked mode requires --peak-5v-a and --continuous-5v-a")
        result = size_5v_supply(
            args.peak_5v_a, args.continuous_5v_a,
            cell_low_v=(3.0 if args.low_cell_v is None else args.low_cell_v),
            measured_boost_efficiency=(
                0.85 if args.measured_efficiency is None else args.measured_efficiency),
            margin=(1.3 if args.margin is None else args.margin),
            boost_max_input_a=args.boost_max_input_a,
            boost_continuous_input_a=args.boost_continuous_input_a,
            boost_continuous_output_a=args.boost_continuous_output_a,
            protected_cell_continuous_a=args.protected_cell_continuous_a,
        )
        if pack_requested:
            result["protected_pack_screen"] = screen_protected_pack(
                result,
                pack_length_mm=args.pack_length_mm,
                pack_width_mm=args.pack_width_mm,
                pack_thickness_mm=args.pack_thickness_mm,
                tray_length_mm=args.tray_length_mm,
                tray_width_mm=args.tray_width_mm,
                tray_height_mm=args.tray_height_mm,
                wire_relief_mm=(8.0 if args.pack_wire_relief_mm is None
                                else args.pack_wire_relief_mm),
                side_clearance_mm=(1.0 if args.pack_side_clearance_mm is None
                                   else args.pack_side_clearance_mm),
                rated_peak_discharge_a=args.pack_peak_discharge_a,
                rated_continuous_discharge_a=args.pack_continuous_discharge_a,
                pcm_overcurrent_trip_a=args.pack_pcm_trip_a,
                connector_continuous_a=args.pack_connector_continuous_a,
                wire_and_crimp_continuous_a=args.pack_wire_crimp_continuous_a,
            )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
