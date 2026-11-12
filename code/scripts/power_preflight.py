"""Conservative full one-pet 1S battery and 5V boost sizing from measured load.

This tool does not recommend a protected cell or charge circuit on speculation.
Use measured simultaneous motor, servo, camera, WiFi and audio load readings.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_CEILING
import json
import math


def size_5v_supply(
    measured_peak_5v_a: float,
    measured_continuous_5v_a: float,
    *,
    cell_low_v: float = 3.0,
    measured_boost_efficiency: float = 0.85,
    margin: float = 1.3,
    boost_max_input_a: float | None = None,
    boost_continuous_output_a: float | None = None,
    protected_cell_continuous_a: float | None = None,
) -> dict:
    values = [
        measured_peak_5v_a, measured_continuous_5v_a,
        cell_low_v, measured_boost_efficiency, margin,
    ]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("All current, efficiency and voltage inputs must be finite")
    if not 0 < measured_continuous_5v_a <= measured_peak_5v_a <= 20:
        raise ValueError("Peak/continuous load missing or invalid")
    if not 2.5 <= cell_low_v <= 4.1:
        raise ValueError("Single-cell low voltage must be measured/qualified")
    if not 0.5 <= measured_boost_efficiency <= 0.99 or not 1 <= margin <= 2:
        raise ValueError("Qualified boost efficiency and current margin required")
    ratings = (boost_max_input_a, boost_continuous_output_a, protected_cell_continuous_a)
    for rating in ratings:
        if rating is not None and (type(rating) not in (int, float)
                                   or not math.isfinite(rating) or rating <= 0):
            raise ValueError("Rated board current must be positive and finite")
    # Decimal input values avoid floating point false equality at a rating
    # boundary. Report required amperes rounded UP, never below actual need.
    required_5v_peak = Decimal(str(measured_peak_5v_a)) * Decimal(str(margin))
    required_cell_peak = (Decimal(5) * required_5v_peak
                          / (Decimal(str(cell_low_v))
                             * Decimal(str(measured_boost_efficiency))))
    required_5v_cont = Decimal(str(measured_continuous_5v_a)) * Decimal(str(margin))
    milliamp = Decimal("0.001")
    boosted_peak = float(required_5v_peak.quantize(milliamp, rounding=ROUND_CEILING))
    cell_peak = float(required_cell_peak.quantize(milliamp, rounding=ROUND_CEILING))
    boosted_cont = float(required_5v_cont.quantize(milliamp, rounding=ROUND_CEILING))
    requirements = {
        "measured_peak_5v_a": measured_peak_5v_a,
        "minimum_rated_5v_output_a": boosted_peak,
        "minimum_rated_cell_and_boost_input_a": cell_peak,
        "minimum_rated_continuous_5v_a": boosted_cont,
        "minimum_protected_cell_discharge_a": cell_peak,
        "charger_and_load_sharing_verified": False,
        "thermal_and_brownout_verified": False,
        "physical_load_verified": False,
    }
    if all(rating is not None for rating in ratings):
        requirements["candidate_electrically_sufficient_on_paper"] = (
            Decimal(str(boost_max_input_a)) >= required_cell_peak
            and Decimal(str(boost_continuous_output_a)) >= required_5v_peak
            and Decimal(str(protected_cell_continuous_a)) >= required_cell_peak
        )
        requirements["candidate_physically_qualified"] = False
    else:
        requirements["candidate_electrically_sufficient_on_paper"] = None
        requirements["candidate_physically_qualified"] = False
    return requirements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peak-5v-a", required=True, type=float)
    parser.add_argument("--continuous-5v-a", required=True, type=float)
    parser.add_argument("--low-cell-v", type=float, default=3.0)
    parser.add_argument("--measured-efficiency", type=float, default=0.85)
    parser.add_argument("--boost-max-input-a", type=float)
    parser.add_argument("--boost-continuous-output-a", type=float)
    parser.add_argument("--protected-cell-continuous-a", type=float)
    args = parser.parse_args()
    result = size_5v_supply(
        args.peak_5v_a, args.continuous_5v_a,
        cell_low_v=args.low_cell_v,
        measured_boost_efficiency=args.measured_efficiency,
        boost_max_input_a=args.boost_max_input_a,
        boost_continuous_output_a=args.boost_continuous_output_a,
        protected_cell_continuous_a=args.protected_cell_continuous_a,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
