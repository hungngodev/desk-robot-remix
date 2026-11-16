"""Conservative full one-pet 1S battery and 5V boost sizing from measured load.

This tool does not recommend a protected cell or charge circuit on speculation.
Use measured simultaneous motor, servo, camera, WiFi and audio load readings.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_CEILING
import json
import math


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
) -> dict:
    """Conservatively bound simultaneous idle system and 1S charge currents.

    TI BQ24074's OUT rail is roughly battery-domain 4.4V, not a 5V rail.
    The charger 1.5A input rating is NOT a 1.5A boosted system plus an
    independent 1.5A charge budget. A separate boost supplies 5V.
    This is a conservative input-current arithmetic gate, not a battery
    charge measurement, thermal/NTC proof or enable signal.
    """
    measured = (measured_idle_5v_a, requested_cell_charge_a, measured_sys_v,
                measured_boost_efficiency, reserve)
    if any(not _finite_number(x) for x in measured):
        raise ValueError("Actual docked loads and conversion measurements required")
    if (not 0 < measured_idle_5v_a <= 20
            or not 0 < requested_cell_charge_a <= 5
            or not 3.0 <= measured_sys_v <= 4.5
            or not 0.5 <= measured_boost_efficiency <= 0.99
            or not 1 <= reserve <= 2):
        raise ValueError("Invalid docked load, cell, SYS or reserve measurement")
    if type(motors_confirmed_disarmed) is not bool:
        raise ValueError("Motor disarm state must be an explicit physical boolean")
    ratings = (charger_input_limit_a, charger_board_thermal_input_a,
               dock_adapter_continuous_a, rated_5v_boost_continuous_a,
               protected_pack_max_charge_a)
    if any(v is not None and (not _finite_number(v) or v <= 0)
           for v in ratings):
        raise ValueError("Positive real component ratings are required")
    decimal = lambda x: Decimal(str(x))
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

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peak-5v-a", required=True, type=float)
    parser.add_argument("--continuous-5v-a", required=True, type=float)
    parser.add_argument("--low-cell-v", type=float, default=3.0)
    parser.add_argument("--measured-efficiency", type=float, default=0.85)
    parser.add_argument("--margin", type=float, default=1.3,
                        help="Conservative current reserve multiplier (1.0 to 2.0)")
    parser.add_argument("--boost-max-input-a", type=float)
    parser.add_argument("--boost-continuous-input-a", type=float)
    parser.add_argument("--boost-continuous-output-a", type=float)
    parser.add_argument("--protected-cell-continuous-a", type=float)
    args = parser.parse_args()
    result = size_5v_supply(
        args.peak_5v_a, args.continuous_5v_a,
        cell_low_v=args.low_cell_v,
        measured_boost_efficiency=args.measured_efficiency,
        margin=args.margin,
        boost_max_input_a=args.boost_max_input_a,
        boost_continuous_input_a=args.boost_continuous_input_a,
        boost_continuous_output_a=args.boost_continuous_output_a,
        protected_cell_continuous_a=args.protected_cell_continuous_a,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
