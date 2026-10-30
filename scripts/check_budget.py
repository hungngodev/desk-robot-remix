"""Report planning allowances separately from a complete purchase quote. No purchases."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def budget(data, shipping=None, tax=None):
    if any(value is not None and value < 0 for value in (shipping, tax)):
        raise ValueError("Shipping and tax must be non-negative")
    total = sum(
        (Decimal(str(row["unit_usd"])) * row["quantity"] for row in data["items"]), Decimal(0)
    )
    unresolved = [
        r["item"] for r in data["items"] if r["price_status"] not in {"verified", "owned"}
    ]
    if shipping is not None and tax is not None:
        total += Decimal(str(shipping)) + Decimal(str(tax))
    complete = not unresolved and shipping is not None and tax is not None
    pending_checks = [name for name, passed in data.get("readiness_checks", {}).items() if not passed]
    return {
        "parts_estimate_usd": float(
            total
            if shipping is None or tax is None
            else total - Decimal(str(shipping)) - Decimal(str(tax))
        ),
        "quoted_total_usd": float(total) if complete else None,
        "planning_total_usd": float(total),
        "cap_usd": data["cap_usd"],
        "remaining_under_cap_usd": float(Decimal(str(data["cap_usd"])) - total),
        "unquoted_items": unresolved,
        "fit_confirmed": data.get("fit_confirmed", False),
        "pending_checks": pending_checks,
        "purchase_ready": complete
        and data.get("fit_confirmed", False)
        and not pending_checks
        and total <= Decimal(str(data["cap_usd"])),
        "note": "Allowances are targets, not verified shopping prices. Confirm mechanical fit separately.",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bom", type=Path, default=ROOT / "hardware/bom.json")
    p.add_argument("--shipping", type=Decimal)
    p.add_argument("--tax", type=Decimal)
    p.add_argument("--require-ready", action="store_true")
    args = p.parse_args()
    result = budget(json.loads(args.bom.read_text()), args.shipping, args.tax)
    print(json.dumps(result, indent=2))
    if args.require_ready and not result["purchase_ready"]:
        p.exit(1, "Complete quotes and fit checks are still needed before ordering.\n")
