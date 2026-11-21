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
