"""Report planning allowances separately from a complete purchase quote. No purchases."""

import argparse
import json
import math
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _money(value, *, label: str) -> Decimal:
    """Finite nonnegative planning money, not a proof of a payable quote."""
    if value is None or type(value) is bool:
        raise ValueError(f"{label} must be a finite non-negative amount")
    try:
        amount = Decimal(str(value))
        # A finite decimal with an impossible exponent must not serialize
        # into infinity in the historical JSON budget view either.
        representable = math.isfinite(float(amount))
    except (InvalidOperation, ValueError, OverflowError, TypeError) as exc:
        raise ValueError(
            f"{label} must be a finite non-negative amount"
        ) from exc
    if not amount.is_finite() or amount < 0 or not representable:
        raise ValueError(f"{label} must be a finite non-negative amount")
    # Historical planning output is converted to JSON floats. Nonzero
    # subcent values must not underflow to an apparent free item or fee.
    # Inspect the Decimal digits directly: quantize() can overflow for
    # finite inputs such as 1e-999999 and must not silently round them.
    if amount and amount.as_tuple().exponent < -2:
        digits = amount.as_tuple().digits
        extra_places = -amount.as_tuple().exponent - 2
        if (extra_places >= len(digits)
                or any(digit != 0 for digit in digits[-extra_places:])):
            raise ValueError(f"{label} must use exact USD cents")
    return amount


def budget(data, shipping=None, tax=None):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("Historical budget needs an items list")
    if data.get("currency", "USD") != "USD":
        raise ValueError("Historical budget currency must be USD")
    cap = _money(data.get("cap_usd"), label="Budget cap")
    freight = _money(shipping, label="Shipping") if shipping is not None else None
    taxes = _money(tax, label="Tax") if tax is not None else None
    fit = data.get("fit_confirmed", False)
    checks = data.get("readiness_checks", {})
    if type(fit) is not bool:
        raise ValueError("Mechanical fit must be a boolean")
    if (not isinstance(checks, dict)
            or any(not isinstance(name, str) or type(passed) is not bool
                   for name, passed in checks.items())):
        raise ValueError("Readiness checks must contain boolean results")
    known_subtotal = Decimal(0)
    unknown_prices = []
    unresolved = []
    for row in data["items"]:
        if not isinstance(row, dict):
            raise ValueError("Historical budget row must be an object")
        name = row.get("item")
        quantity = row.get("quantity")
        status = row.get("price_status")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Every budget item needs a nonempty name")
        if type(quantity) is not int or quantity <= 0:
            raise ValueError(f"{name}: quantity must be a positive integer")
        if not isinstance(status, str) or not status.strip():
            raise ValueError(f"{name}: price status is required")
        if row.get("currency", "USD") != "USD":
            raise ValueError(f"{name}: budget currency must be USD")
        price = row.get("unit_usd")
        if price is None:
            unknown_prices.append(name)
        else:
            known_subtotal += _money(price, label=f"{name} unit price") * quantity
        if status not in {"verified", "owned"} or price is None:
            unresolved.append(name)
    # A collection of individually finite prices may still overflow a
    # normal JSON number. Never present infinite headroom as a valid result.
    if not math.isfinite(float(known_subtotal)):
        raise ValueError("Historical budget subtotal is not finite")
    total = known_subtotal
    unknown_fees = []
    for label, fee in (("shipping", freight), ("tax", taxes)):
        if fee is None:
            unknown_fees.append(label)
        else:
            total += fee
    if not math.isfinite(float(total)):
        raise ValueError("Historical budget total is not finite")
    all_costs_known = not unknown_prices and not unknown_fees
    complete = not unresolved and all_costs_known
    pending_checks = [name for name, passed in checks.items() if not passed]
    return {
        "known_subtotal_usd": float(known_subtotal),
        "known_landed_subtotal_usd": float(total),
        "unknown_landed_fees": unknown_fees,
        "planning_over_cap": True if total > cap else (False if all_costs_known else None),
        "unknown_price_items": unknown_prices,
        "parts_estimate_usd": None if unknown_prices else float(known_subtotal),
        "quoted_total_usd": float(total) if complete else None,
        "planning_total_usd": None if unknown_prices else float(total),
        "cap_usd": data["cap_usd"],
        "remaining_under_cap_usd": (
            float(cap - total) if all_costs_known else None
        ),
        "unquoted_items": unresolved,
        "fit_confirmed": fit,
        "pending_checks": pending_checks,
        "purchase_ready": complete and fit and not pending_checks and total <= cap,
        "note": (
            "Missing prices and fees remain unknown; known landed subtotal includes "
            "only supplied costs. "
            "Allowances are targets, not verified shopping prices. Confirm mechanical fit separately."
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bom", type=Path, help="Explicit historical/custom budget only")
    p.add_argument("--shipping", type=Decimal)
    p.add_argument("--tax", type=Decimal)
    p.add_argument("--require-ready", action="store_true")
    args = p.parse_args()
    if args.bom is None:
        # Never let the superseded bom.json drive the default shopping path.
        # Current parts, motor alternatives and unquoted physical roles come
        # from the one canonical source used by procurement_release.py.
        from procurement_release import (
            PLAN,
            _load_cli_json,
            first_robot_projection,
            generate,
            pilot_supplier_cart,
        )

        if args.shipping is not None or args.tax is not None:
            p.error("Current first-unit landed prices require verified receipts; "
                    "--shipping/--tax are only valid with an explicit --bom")
        report = generate(_load_cli_json(PLAN, "canonical plan"))
        first = first_robot_projection(report)
        cart = pilot_supplier_cart(report)
        print(json.dumps({
            "source": "canonical full-feature-plan.json",
            "first_robot": first,
            "evaluation_cart": cart,
            "purchase_ready": False,
            "landed_total_usd": None,
            "note": "Evaluation quotes are not delivered prices. Use "
                    "procurement_release.py --require-first-robot with "
                    "verified physical evidence for a purchase release.",
        }, indent=2))
        if args.require_ready:
            p.exit(2, "HOLD: use the strict first-robot receipt verifier; "
                      "historical quotes cannot authorize an order.\n")
    else:
        from procurement_release import _load_cli_json

        try:
            result = budget(
                _load_cli_json(args.bom, "historical budget"),
                args.shipping,
                args.tax,
            )
        except (ValueError, KeyError) as exc:
            p.error(f"Invalid historical budget: {exc}")
        # Explicit historical math is useful for comparison, but even an
        # entirely green synthetic legacy file has no purchase authority.
        result["historical_math_ready"] = result["purchase_ready"]
        result["purchase_ready"] = False
        result["source"] = "explicit_legacy_bom_not_release_authority"
        print(json.dumps(result, indent=2))
        if result["planning_over_cap"] is True:
            print("WARNING: known planning costs exceed the USD cap.", file=sys.stderr)
        if args.require_ready:
            p.exit(2, "HOLD: legacy BOM cannot approve a purchase. Use "
                      "the strict canonical first-robot receipt verifier.\n")
