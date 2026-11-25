**Single procurement authority:** The machine plan is [full-feature-plan.json](docs/hardware/full-feature-plan.json). The [owned and remaining lists](docs/hardware/complete-shopping-checklist.md) and [fleet CSV](docs/hardware/fleet-components.csv) are generated views, not independently editable shopping decisions. The 2026-11-04 $50 prototype quote and earlier sensor/mux counts are historical. Current full five-robot purchase approval is **HOLD** until loaded drive, actual power/charging, optics, fit, voice and physical trials are qualified.

**Read-only preview (ordinary builders, no files overwritten):**

```sh
python3 code/scripts/procurement_release.py --format first-robot-markdown
python3 code/scripts/procurement_release.py --format pilot-cart-markdown
```

**Atomic regeneration (maintainers only; preserves existing views on any failure):**

```sh
tmp_md="$(mktemp docs/hardware/.complete-shopping-checklist.md.XXXXXX)" && \
tmp_csv="$(mktemp docs/hardware/.fleet-components.csv.XXXXXX)" && \
trap 'rm -f "$tmp_md" "$tmp_csv"' EXIT && \
python3 code/scripts/procurement_release.py --format markdown > "$tmp_md" && \
python3 code/scripts/procurement_release.py --format csv > "$tmp_csv" && \
mv "$tmp_md" docs/hardware/complete-shopping-checklist.md && \
mv "$tmp_csv" docs/hardware/fleet-components.csv && \
trap - EXIT && \
python3 -m pytest code/tests/test_procurement_release.py
```

# Desk Robot Remix

**First complete pet builder route:** [One robot, dock and shared station assembly and acceptance guide](docs/guides/one-complete-robot.md). This entry point links the canonical two shopping lists, printable reference geometry, wiring, firmware, calibration and physical HOLD gates. It is not a finished printable or powered hardware release.

- [**Docs**](docs/README.md) is the living handbook. Start here for the plan,
  parts, model files, build guides, sources and bench records.
- [**Code**](code/README.md) contains the firmware, Mac software, tools and
  automated tests.

**Selected full five-pet hardware wiring and purchasing plan:** [short copyable shopping checklist](docs/hardware/complete-shopping-checklist.md), [per-robot pin map and shopping list](docs/hardware/full-feature-wiring-and-shopping.md), [machine-readable component allocation](docs/hardware/full-feature-plan.json). Firmware support for optional expansion modules and physical validation remain open.

**Complete final design before assembly:** [day-zero full-feature blueprint](docs/README.md#full-final-project-contract-and-scope) covers the forward-only build, 200 feature and sensor ideas, 131 original research URLs, upstream reuse, unresolved decisions and measured acceptance. The original docs and code remain the source records.
