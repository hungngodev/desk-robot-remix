# Parts and cost — 2026-10-28

The active build uses separate head modules and an existing EVA printed case.
The draft totals **$117.33 before shipping/tax**, with a **$150 first-robot cap**
including charges and any purchased bench supply. This is a planning list, not
a complete quoted cart. No CoreS3 purchase is required.

| Item | Qty | Line total USD | Status |
| --- | ---: | ---: | --- |
| [Freenove FNK0085B S3 camera board](https://store.freenove.com/products/fnk0085?variant=44552293155014) | 1 | 21.99 | Exact 16 MB flash / 8 MB PSRAM variant price; camera sensor/lens fit unresolved |
| [1.3-inch SH1106 I²C OLED, DSP-9](https://protosupplies.com/product/oled-1-3-128x64-i2c-blue-display/) | 1 | 5.95 | Observed seller quote; 35.4×33.5 mm PCB; mounting fit provisional |
| [INMP441 microphone breakout](https://www.sinoning.com/product/omnidirectional-microphone-module-i2s-interface-inmp441-mems-high-precision-low-power-ultra-small-volume-for-esp32/) | 1 | 2.09 | Observed seller quote; exact PCB fit and delivery unverified |
| [MAX98357A amplifier, PID3006](https://www.adafruit.com/product/3006) | 1 | 5.95 | Observed price; board mounting provisional |
| Compact 4–8 Ω speaker | 1 | 3.00 | $2–4 allowance; exact size/power unresolved |
| Existing ESP32-WROOM-32 | 1 | 0.00 | Owned |
| [Adafruit SG92R PID169](https://www.adafruit.com/product/169) | 2 | 11.90 | $5.95 each; fit provisional |
| [Adafruit DRV8833 PID3297](https://www.adafruit.com/product/3297) | 1 | 5.95 | Verified price |
| 6 V N20, 150–200 rpm, 3 mm D shaft | 2 | 16.00 | Allowance; exact affordable SKU needed |
| [DFRobot DFR0205 buck](https://www.dfrobot.com/product-752.html) | 1 | 8.50 | Verified price; clearance needed |
| [DFRobot DFR0564 2S charger](https://www.dfrobot.com/product-1713.html) | 1 | 5.00 | Conditional on pack compatibility |
| Assembled protected/balanced 2S pack | 1 | 16.00 | Allowance; pack not selected |
| Switch, wires, connectors, fasteners | — | 8.00 | Allowance |
| Filament, including EVA head case | — | 5.00 | Allowance; assumes printer access; slicer mass not checked |
| Suppression/decoupling components | — | 2.00 | Allowance |
| **Parts estimate** | | **117.33** | **$32.67 left for charges/changes** |

Head electronics are **$37.98–39.98**, using the $3 speaker midpoint above.
The separate-module route saves about $5–7 versus the earlier $44.90 head at
these retail references; larger savings are not verified. Consolidate suppliers
where the exact module matches, because multiple shipping charges can erase
that difference. [Case, dimensions, wiring and firmware status](../docs/modular-head.md).

The dimensioned [Pololu 2368](https://www.pololu.com/product/2368/specs) motor is
$23.95 each at the earlier check. Using two raises this estimate to **$149.23
before tax/shipping**, leaving just $0.77 under the cap for charges. Do not
silently substitute it or use TT motors that do not fit.

The gripper photos show SG90-style servos. SG92R is a priced candidate, not a
verified drop-in replacement: measure case, ears, shaft height and matching horn
spline before printing. Flat-key clearance and lift performance are unverified.

The OLED is monochrome. Stock software shows emotion symbols and text; smooth
eye animation needs another adapter. It does not provide a color LCD.
The camera is included with the candidate Freenove board, but the seller does
not identify the current sensor/lens assembly. Confirm it against EVA's camera
opening before ordering. Display PCB holes, speaker dimensions and head-to-rover
clearance are unverified. The original case is saved; no new case design is planned.

DFR0205 is 46 × 50 × 20 mm. Its advertised 5 A rating does not establish sustained
performance inside this rover. DFR0564 is an unbalanced charger: use only if the
final pack manufacturer confirms compatible charging, protection and balancing.
[Charger instructions](https://wiki.dfrobot.com/dfr0564/docs/19979). This selection
is unresolved; no battery or charger has been bought.

Borrow a suitable regulated supply for the gripper test if available; otherwise
add its real price. Replace allowances in `bom.json` with actual quotes, verify
mechanical fit and include every order charge before treating the cap as met:

```sh
python3 scripts/check_budget.py
python3 scripts/check_budget.py --shipping 12 --tax 9 --require-ready
```

The second command fails while quotes/fit are incomplete. No parts were purchased.
