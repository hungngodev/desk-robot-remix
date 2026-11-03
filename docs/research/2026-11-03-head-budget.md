# Head and budget verification — 2026-11-03

The user owns classic ESP32-WROOM-32 boards and **no ESP32-S3**. The Sense board below is a proposed purchase. It does not make the existing Freenove firmware compatible without a board configuration change and a successful build/bench test.

## Exact head candidate

The [official Seeed shop](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html) lists **XIAO ESP32-S3 Sense, SKU 113991115, $13.99 USD**, in stock at this check. This is the Sense bundle with camera/digital-microphone hardware, not the bare XIAO ESP32-S3, a camera-only accessory, or an expansion-board-only purchase. Shipping and tax were not obtained; no cart or purchase was made.

The [official getting-started documentation](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/) specifies **8 MB flash and 8 MB PSRAM**. Boards can ship with **OV3660 or OV5640 autofocus** during the transition; OV2640 is discontinued. The stack is 21 × 17.8 × 15 mm. The microphone is **PDM**, GPIO42 clock / GPIO41 data. SD uses GPIO7/8/9 and chip select21. Confirm the actual camera, disable SD if reusing its pins, and reserve camera/microphone connections.

Our preliminary allocation is two OLED signals, three amplifier signals and two UART signals: seven exposed GPIO. This is an engineering proposal, not a tested circuit. Check strapping and optional touch input against the schematic. A Sense-specific SSD1306/PDM/camera configuration and an 8 MB partition layout must replace the old Freenove map and pass build/bench tests before flashing.

## Small audio parts

The [ElectroPeak MAX98357 I²S amplifier](https://electropeak.com/max98357-i2s-audio-amplifier-module), SKU **SEN-17-139**, is **$1.95**. Verify the supplied chip variant and board pin labels; the listing title alone does not certify the MAX98357A variant. Connect the speaker across the differential speaker outputs, never from one output to ground.

The [ElectroPeak 8 Ω / 1 W speaker](https://electropeak.com/8-ohm-1w-20mm-diameter-speaker), SKU **SEN-17-105**, is **$0.29**, 20 mm diameter × 3.75 mm thick, with solder pads. Limit amplifier volume appropriately and measure the existing head cavity. Both prices and stock metadata were retrieved directly from the seller HTML on this date after the web text renderer timed out on follow-up requests. These are item prices, not delivered quotes.

Sense + amplifier + speaker totals **$16.23**. The owned SSD1306 eliminates the planned new SH1106 purchase; the Sense microphone eliminates the separate INMP441 purchase. Quantity and condition of the owned OLED and MG90S servos still need confirmation before scaling to five.

## Conditional prototype arithmetic

| Entry | USD |
| --- | ---: |
| Sense camera/microphone bundle | 13.99 |
| Amplifier + speaker | 2.24 |
| Five ToF sensors at $1.75 | 8.75 |
| One I²C multiplexer | 0.47 |
| Power leads, switch, connectors and fasteners allowance | 8.00 |
| Decoupling allowance | 2.00 |
| **Conditional parts target** | **35.45** |

The sensor quotes and mounting qualifications belong in [cliff-sensors](2026-11-03-cliff-sensors.md). This total assumes two usable owned steppers/drivers, two usable owned MG90S servos, a usable owned OLED, one WROOM, filament and a suitable power bank. **The servo quantity and bank capacity are unknown**. The $14.55 remainder under the $50 delivered cap must cover all delivery, tax and missing items; it is not proof that the final order will fit. Five times the prototype target is not a complete fleet quote: only five of the ten required steppers/drivers are reported owned, and other fleet counts are unknown.

## Existing budget checker contract

[scripts/check_budget.py](../../scripts/check_budget.py) reads an object containing `items`, `cap_usd`, optional `fit_confirmed` and optional boolean `readiness_checks`. Each item requires numeric `unit_usd`, numeric `quantity`, `item` and `price_status`. A null price will fail decimal conversion. Statuses other than `verified` or `owned` are reported unresolved, so `inventory_check` is suitable for a conditional zero-dollar reuse assumption with an unknown owned count. Mark allowances as `allowance`, not `verified`.

`purchase_ready` additionally requires shipping and tax arguments, confirmed fit, all readiness checks true, and a total within the cap. Item price verification alone cannot make the design order-ready. Use procurement readiness for exact-variant feasibility, servo inventory and preliminary fit/power checks. Keep completed builds, physical fit, sensor stopping and integrated power tests in separate qualification fields that gate roaming/fleet duplication, so the first sample purchase does not depend on tests requiring those samples. No runtime or checker code was changed for this research.
