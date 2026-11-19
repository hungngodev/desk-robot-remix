"""Report planning allowances separately from a complete purchase quote. No purchases."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def budget(data, shipping=None, tax=None):
    if any(value is not None and value < 0 for value in (shipping, tax)):
        raise ValueError("Shipping and tax must be non-negative")
    unknown_prices = [row["item"] for row in data["items"] if row.get("unit_usd") is None]
    known_subtotal = sum(
        (Decimal(str(row["unit_usd"])) * row["quantity"]
         for row in data["items"] if row.get("unit_usd") is not None), Decimal(0)
    )
    total = known_subtotal
    unresolved = [
        r["item"] for r in data["items"]
        if r["price_status"] not in {"verified", "owned"} or r.get("unit_usd") is None
    ]
    if shipping is not None and tax is not None:
        total += Decimal(str(shipping)) + Decimal(str(tax))
    complete = not unresolved and shipping is not None and tax is not None
    pending_checks = [name for name, passed in data.get("readiness_checks", {}).items() if not passed]
    return {
        "known_subtotal_usd": float(known_subtotal),
        "unknown_price_items": unknown_prices,
        "parts_estimate_usd": None if unknown_prices else float(known_subtotal),
        "quoted_total_usd": float(total) if complete else None,
        "planning_total_usd": None if unknown_prices else float(total),
        "cap_usd": data["cap_usd"],
        "remaining_under_cap_usd": (
            None if unknown_prices else float(Decimal(str(data["cap_usd"])) - total)
        ),
        "unquoted_items": unresolved,
        "fit_confirmed": data.get("fit_confirmed", False),
        "pending_checks": pending_checks,
        "purchase_ready": complete
        and data.get("fit_confirmed", False)
        and not pending_checks
        and total <= Decimal(str(data["cap_usd"])),
        "note": (
            "Missing prices remain unknown; known subtotal is not a whole-robot total. "
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
            first_robot_projection,
            generate,
            pilot_supplier_cart,
        )

        if args.shipping is not None or args.tax is not None:
            p.error("Current first-unit landed prices require verified receipts; "
                    "--shipping/--tax are only valid with an explicit --bom")
        report = generate(json.loads(PLAN.read_text(encoding="utf-8")))
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
        result = budget(json.loads(args.bom.read_text()), args.shipping, args.tax)
        # Explicit historical math is useful for comparison, but even an
        # entirely green synthetic legacy file has no purchase authority.
        result["historical_math_ready"] = result["purchase_ready"]
        result["purchase_ready"] = False
        result["source"] = "explicit_legacy_bom_not_release_authority"
        print(json.dumps(result, indent=2))
        if args.require_ready:
            p.exit(2, "HOLD: legacy BOM cannot approve a purchase. Use "
                      "the strict canonical first-robot receipt verifier.\n")
