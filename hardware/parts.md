# Parts and cost — 2026-10-28

Target **$100–140 per robot before shipping/tax**, with a **$150 first-robot cap**.
The draft totals **$123.25**. Shipping/tax and any purchased bench supply must fit
inside the cap. This is a planning list, not a complete quoted cart.

| Item | Qty | Line total USD | Status |
| --- | ---: | ---: | --- |
| [CoreS3 Lite K128-LITE](https://shop.m5stack.com/products/m5stack-cores3-lite-esp32s3-iot-dev-kit) | 1 | 44.90 | Verified price; recheck stock |
| Existing ESP32-WROOM-32 | 1 | 0.00 | Owned |
| [Adafruit SG92R PID169](https://www.adafruit.com/product/169) | 2 | 11.90 | $5.95 each; fit provisional |
| [Adafruit DRV8833 PID3297](https://www.adafruit.com/product/3297) | 1 | 5.95 | Verified price |
| 6 V N20, 150–200 rpm, 3 mm D shaft | 2 | 16.00 | Allowance; exact affordable SKU needed |
| [DFRobot DFR0205 buck](https://www.dfrobot.com/product-752.html) | 1 | 8.50 | Verified price; clearance needed |
| [DFRobot DFR0564 2S charger](https://www.dfrobot.com/product-1713.html) | 1 | 5.00 | Conditional on pack compatibility |
| Assembled protected/balanced 2S pack | 1 | 16.00 | Allowance; pack not selected |
| Switch, wires, connectors, fasteners | — | 8.00 | Allowance |
| Filament | — | 5.00 | Allowance; assumes printer access |
| Suppression/decoupling components | — | 2.00 | Allowance |
| **Parts estimate** | | **123.25** | **$26.75 left for charges/changes** |

The dimensioned [Pololu 2368](https://www.pololu.com/product/2368/specs) motor is
$23.95 each. Using two raises this estimate to **$155.15 before tax/shipping**,
over the cap. Do not silently substitute it or use TT motors that do not fit.

The gripper photos show SG90-style servos. SG92R is a priced candidate, not a
verified drop-in replacement: measure case, ears, shaft height and matching horn
spline before printing. Flat-key clearance and lift performance are unverified.

CoreS3 **Lite** includes camera, LCD, microphones and speaker; **SE** is different.
The [manufacturer revision notes](https://docs.m5stack.com/en/core/CoreS3-Lite)
report an August 2026 LCD change, which needs checking on the actual head.

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
