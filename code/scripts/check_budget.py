"""Report planning allowances separately from a complete purchase quote. No purchases."""

import argparse
import json
import math
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from landed_cost import MAX_ACCOUNTING_UNITS, MAX_ACCOUNTING_USD, cents, landed_total_cents

ROOT = Path(__file__).resolve().parents[1]

# Match the canonical landed-cost receipt limits; historical JSON floats
# additionally require the aggregate to stay within the same cent-safe bound.
MAX_BUDGET_USD = MAX_ACCOUNTING_USD
MAX_BUDGET_CENTS = int(MAX_BUDGET_USD) * 100
MAX_BUDGET_UNITS = MAX_ACCOUNTING_UNITS


def _money(value: object, *, label: str) -> int:
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
    if amount > MAX_BUDGET_USD:
        raise ValueError(f"{label} exceeds historical USD bound")
    try:
        return cents(amount, label)
    except ValueError as exc:
        raise ValueError(f"{label} must use exact USD cents") from exc


def _item_totals(items: list[object]) -> tuple[int, list[str], list[str]]:
    """Validate historical rows and return known cents and unresolved item names."""
    known_subtotal = 0
    unknown_prices: list[str] = []
    unresolved: list[str] = []
    for row in items:
        if not isinstance(row, dict):
            raise ValueError("Historical budget row must be an object")
        name = row.get("item")
        quantity = row.get("quantity")
        status = row.get("price_status")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Every budget item needs a nonempty name")
        if type(quantity) is not int or quantity <= 0:
            raise ValueError(f"{name}: quantity must be a positive integer")
        if quantity > MAX_BUDGET_UNITS:
            raise ValueError(f"{name}: quantity exceeds historical unit bound")
        if not isinstance(status, str) or not status.strip():
            raise ValueError(f"{name}: price status is required")
        if row.get("currency", "USD") != "USD":
            raise ValueError(f"{name}: budget currency must be USD")
        price = row.get("unit_usd")
        unit_cents = None if price is None else _money(price, label=f"{name} unit price")
        # Only explicitly owned stock can use a zero historical price.
        # A zero placeholder for a new purchase is an unknown quote.
        if unit_cents == 0 and status != "owned":
            unit_cents = None
        if unit_cents is None:
            unknown_prices.append(name)
        else:
            known_subtotal += unit_cents * quantity
        if status not in {"verified", "owned"} or unit_cents is None:
            unresolved.append(name)
    # Bound aggregate costs too, so JSON floats retain cent resolution.
    if known_subtotal > MAX_BUDGET_CENTS:
        raise ValueError("Historical budget subtotal exceeds historical USD bound")
    return known_subtotal, unknown_prices, unresolved


def budget(data: object, shipping: object = None, tax: object = None) -> dict[str, object]:
    """Report historical planning costs without granting purchase authority."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("Historical budget needs an items list")
    if not data["items"]:
        raise ValueError("Historical budget needs at least one item")
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
    known_subtotal, unknown_prices, unresolved = _item_totals(data["items"])
    unknown_fees = [
        label for label, fee in (("shipping", freight), ("tax", taxes)) if fee is None
    ]
    # Unknown fees remain explicit; zero here contributes only to the known floor.
    total = landed_total_cents(
        known_subtotal, shipping=freight or 0, tax=taxes or 0, duties=0, discount=0,
    )
    if total > MAX_BUDGET_CENTS:
        raise ValueError("Historical budget total exceeds historical USD bound")
    all_costs_known = not unknown_prices and not unknown_fees
    complete = not unresolved and all_costs_known
    pending_checks = [name for name, passed in checks.items() if not passed]
    return {
        "known_subtotal_usd": known_subtotal / 100,
        "known_landed_subtotal_usd": total / 100,
        "unknown_landed_fees": unknown_fees,
        "planning_over_cap": True if total > cap else (False if all_costs_known else None),
        "unknown_price_items": unknown_prices,
        "parts_estimate_usd": None if unknown_prices else known_subtotal / 100,
        "quoted_total_usd": total / 100 if complete else None,
        "planning_total_usd": None if unknown_prices else total / 100,
        "cap_usd": cap / 100,
        "remaining_under_cap_usd": (
            (cap - total) / 100 if all_costs_known else None
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


def _load_historical_json(path: Path) -> object:
    """Reuse strict parser hooks but retain exact decimal tokens for money."""
    from procurement_release import (
        _finite_json_float,
        _reject_json_constant,
        _unique_json_object,
    )

    def exact_float(token: str) -> Decimal:
        _finite_json_float(token)  # Preserve existing finite-range rejection.
        return Decimal(token)

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_float=exact_float,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, ValueError, InvalidOperation) as exc:
        raise ValueError(f"historical budget JSON is invalid or ambiguous: {exc}") from exc


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
        hypothetical_excess = cart["historical_first_unit_budget"][
            "historical_over_cap_before_tax_shipping_usd"
        ]
        if hypothetical_excess > 0:
            print(
                f"WARNING: hypothetical historical sample selection exceeds the USD cap "
                f"by ${hypothetical_excess:.2f} before tax and shipping; "
                "not incurred spending or a current quote.",
                file=sys.stderr,
            )
        if args.require_ready:
            p.exit(2, "HOLD: use the strict first-robot receipt verifier; "
                      "historical quotes cannot authorize an order.\n")
    else:
        try:
            result = budget(
                _load_historical_json(args.bom),
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
