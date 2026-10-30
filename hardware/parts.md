# Budget components — five identical cores

Updated 2026-10-30. **First prototype parts target: $36.88; delivered cap: $50.**
This assumes one owned WROOM and a usable owned USB power bank. Delivery/tax,
three allowances and the cheap camera board's compatibility remain unresolved.
**This is not an order-ready $50 robot.** No purchase has been made.

| Component | Per robot | For five | First-robot USD | Quote / requirement |
| --- | ---: | ---: | ---: | --- |
| [S3 N16R8 + OV2640 camera candidate](https://www.aliexpress.com/item/1005007884506760.html) | 1 | 5 | 7.11 | PCBFUN: select **Module and OV2640**; $5.60 shipping shown for one; pinout/programming/case fit unqualified |
| [1.3-inch SH1106 four-pin I²C OLED](https://electropeak.com/1-3-i2c-128x64-white-oled-display-module) | 1 | 5 | 2.98 | LCD-01-103, 35.4×33.5 mm PCB; monochrome; measure mounts |
| [INMP441 microphone](https://www.sinoning.com/product/omnidirectional-microphone-module-i2s-interface-inmp441-mems-high-precision-low-power-ultra-small-volume-for-esp32/) | 1 | 5 | 2.09 | 3.3 V; footprint/port check |
| [Generic MAX98357 I²S amplifier](https://electropeak.com/max98357-i2s-audio-amplifier-module) | 1 | 5 | 1.95 | SEN-17-139; confirm I²S variant and dimensions |
| [20 mm 8 Ω / 1 W speaker](https://electropeak.com/8-ohm-1w-20mm-diameter-speaker) | 1 | 5 | 0.29 | SEN-17-105; 3.75 mm thick, solder pads; mount/acoustic fit unverified |
| Existing ESP32-WROOM-32 | 1 | 5 | 0.00 | One confirmed owned; exact fleet count unknown |
| [SG90 positional servo](https://www.sinoning.com/product/1pcs-sg90-9g-mini-micro-servo-for-rc-250-450-helicopter-airplane-car-robot/) | 2 | 10 | 2.98 | $1.49 each; lift + grip; includes horns/screws per seller |
| [N20 3–6 V geared motor](https://www.sinoning.com/product/1pcs-n20-micro-reducer-motor-5v-6v-3v-dc-long-shaft-reducer-motor-metal-gear/) | 2 | 10 | 3.98 | $1.99 each; 3 mm D shaft; 100 rpm at 6 V/no load; slower at 5 V |
| [Generic DRV8833 dual driver](https://www.sinoning.com/product/drv8833-2channel-dc-motor-driver-module-board-1-5a-3v-10v/) | 1 | 5 | 0.50 | Actual continuous current and sleep/fault wiring need checking |
| Existing regulated USB power bank | 1 | 5 | 0.00 | One owned; rating, weight, fit and exact fleet count unknown |
| Rated USB power lead, switch, wiring, connectors, screws | 1 set | 5 sets | 8.00 | **Allowance**, includes actuator power branch |
| Filament for existing body, arm, head and small mounts | 1 set | 5 sets | 5.00 | **Allowance**; printer access assumed, sliced mass unmeasured |
| Suppression capacitors / decoupling | 1 set | 5 sets | 2.00 | **Allowance**, selected after current/noise tests |
| **Parts target** | | | **36.88** | **$13.12 remains for all shipping/tax/changes** |

The head target is $14.42. The two servos, two motors and driver total **$7.46**.
The old $117.33 branded-retail BOM is archived in
[archive/bom-retail-2026-10-28.json](archive/bom-retail-2026-10-28.json).
Removing the separate 2S pack, charger and buck saves $29.50 **only if the owned
5 V bank can support the robot and mount without destabilizing it**.

## What is actually compatible

The original [Bluino arm](https://www.thingiverse.com/thing:4253681) uses SG90-style
positional servos. Use ordinary **180° SG90s**, one for lift and one for grip;
360° continuous-rotation servos cannot hold commanded arm angles. Check the actual
case, spline, travel and load before duplicating the build. Claimed stall torque
is not a demonstrated key-lifting capacity.

Keep N20 motors for [SMARS](https://www.thingiverse.com/thing:2662828). Yellow TT
motors and continuous servos require new drivetrain mounts; they are not a
minimal change to this chassis. The cheap N20's 50 mA figure is **no-load current**,
not stall current. Verify startup/load current and driver temperature.

The $7.11 camera bundle is a **price lead**, not a qualified substitute for the
compiled Freenove N16R8 target. Confirm the camera wiring and that every GPIO in
[modular-head.md](../docs/modular-head.md) is available, plus programming and the
EVA case mount. The seller PDF could not be retrieved. An accessory-only $1.53
option and a separate $6.45 board-only listing were rejected as complete-camera
prices. Do not buy five or flash the reference firmware based on the title.
The official [Freenove N16R8 reference](https://store.freenove.com/products/fnk0085?variant=44552293155014)
was $21.99 at the earlier check; using it raises this target to **$51.76 before
shipping/tax**, above the current cap. It remains a technical reference.

## Five-unit cost and inventory

Five times the present first-robot parts target is **$184.40**, before delivery/tax
and any additional WROOM boards or power banks. This is arithmetic, **not a verified
five-robot quote**: no five-unit price/shipping has been checked and only one owned
bank/controller is confirmed. Record exact owned counts in
[fleet-inventory.json](fleet-inventory.json), then price the missing quantities.
The procurement quantities are in [fleet-components.csv](fleet-components.csv).
Every robot gets its own camera, speaker, screen, lift and gripper.

Do not treat bulk discounts, one-per-customer offers or the same power bank as
five independent power supplies. ElectroPeak's advertised free shipping starts
above $100; this prototype order does not automatically qualify. Consolidate
suppliers where parts match and reject a delivered cart over $50.

```sh
python3 scripts/check_budget.py
python3 scripts/check_budget.py --shipping 5.60 --tax 0 --require-ready
```

The second command still fails: $5.60 covers only the observed camera-board
shipping, not the other vendors, and compatibility/fit/quotes are open.
See [the ten-check audit](../docs/budget-audit.md) and [power wiring](wiring.md).
