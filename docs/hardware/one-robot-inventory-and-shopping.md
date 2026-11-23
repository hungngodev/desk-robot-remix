# First complete robot procurement entry point

This file intentionally contains **no independently maintained shopping rows**.
A manual one-robot table drifted away from the accepted hardware plan, so it is
retired as a cart rather than allowed to become a third source of truth.

The only static builder-facing lists are the two sections in
[complete-shopping-checklist.md](complete-shopping-checklist.md):

1. reported owned or ordered, still unverified
2. remaining components or unqualified roles

Both come from
[full-feature-plan.json](full-feature-plan.json) through
`code/scripts/procurement_release.py`.

For the exact one-robot, one-dock and one-shared-station projection, use the
same generator instead of copying quantities into this file:

```bash
cd code
uv run --no-sync python scripts/procurement_release.py --format first-robot-markdown
```

The first-unit projection preserves reported stock separately from verified
stock, keeps conditional room options at zero until selected, and cannot lift
supplier, fit, electrical, power, charging or physical safety HOLDs. The
original photographs and ownership evidence remain in the dedicated
[photo inventory](photo-inventory-2026-11-04.md).


## Strict first-unit prior spending reconciliation

The nonstrict two-list preview stays available without private receipts. Before
using `--require-first-robot` to request a checkout release, independently
reconcile **every** earlier Desk Robot Remix purchase. The verified one-Sense
USD 13.67 payment is only the known minimum, not proof that other purchases
never occurred. Account for the actual delivered price, shipping, tax and
discounts of every earlier paid order without double-counting received stock.

In the private operator evidence JSON, `costs.paid_orders_complete` must be
`true` only after review of the whole payment history. Its
`costs.prior_spend_review` object must carry these fields:

| Field | Required meaning |
| --- | --- |
| `scope` | Literal `all_desk_robot_remix_prior_paid_orders` |
| `all_project_prior_spend_reconciled` | Boolean `true` only after an actual review |
| `review_basis` | Literal `private_invoices_and_payment_statements` |
| `reviewer` | An accountable non-generic reviewer name; not `operator` or `fixture` |
| `review_record_id` | Reference to the operator's private evidence ledger |
| `reviewed_on` | Actual ISO calendar date of review, not a future date |
| `reconciled_total_usd` | The **exact** prior paid sum as a decimal USD string, including all orders |
| `paid_orders_sha256` | SHA256 of the exact ordered `costs.paid_orders` JSON array in canonical form |
| `private_receipts_manifest_sha256` | SHA256 of a reviewer-held private receipt manifest, lowercase hex |

Compute the register digest from the final evidence file, without publishing
payment statements or raw transaction identifiers:

```bash
python3 - /private/path/checkout-evidence.json <<'PY'
import hashlib
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    orders = json.load(source)["costs"]["paid_orders"]
canonical = json.dumps(
    orders, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
print(hashlib.sha256(canonical).hexdigest())
PY
shasum -a 256 /private/path/redacted-receipts-manifest.json
```

Use the actual digest of the private manifest, not a synthetic test value.
Keep that manifest and the underlying invoices in private operator storage.
Only the digest, review metadata and opaque evidence reference belong in the
checkout input. The source gate checks chronology, totals and changed-register
detection. **A digest or self-attestation alone cannot prove that a reviewer
actually examined every receipt.** Do not mark the review complete until the
operator has accounted for the full prior spending history. A fresh reviewed
record supersedes the canonical older `all_project_prior_spend_reconciled=false`
status only for that signed checkout; it does not change old paid history.

Even a complete spend review does not authorize a purchase by itself.
The strict command still requires selected carriers, seller-delivered quotes,
independent fitting and physical receipts, exact revision CI, and the remaining
power, dock and safety gates.
