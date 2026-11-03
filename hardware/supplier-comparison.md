# All missing electronics — Amazon versus direct suppliers

Rechecked 2026-11-03, USD. Reuse the owned WROOM, SSD1306 OLED, two existing
28BYJ/ULN2003 pairs, two positional MG90S, filament and signal wires for the
first prototype. The user's estimate is about ten MG90S total. Bank model/current
remain unknown; suitable portable power is still a qualification gate.

| Component needed for one | Amazon package purchase | Outside purchase of required quantity |
| --- | --- | --- |
| One Sense camera/mic head | [1 board, $25.99](https://www.amazon.com/dp/B0C69FFVHH) | [Seeed, 1 board, $13.90](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html) |
| Five VL53L0X sensors | [5-pack, $13.99](https://www.amazon.com/dp/B0F28MFW6X) | [ElectroPeak, 5 × $1.75 = $8.75](https://electropeak.com/gy-530-vl53l0x-laser-ranging-sensor-module-double-hole) |
| One I²S amplifier | [2-pack, $6.88](https://www.amazon.com/dp/B0DPJRLMDJ) | [ElectroPeak, 1 × $1.95](https://electropeak.com/max98357-i2s-audio-amplifier-module) |
| One I²C multiplexer | [3-pack, $6.98](https://www.amazon.com/dp/B0F8ZB8DNM) | [ElectroPeak, 1 × $0.47](https://electropeak.com/tca9548a-1-to-8-i2c-8-way-multi-channel-expansion-board) |
| One20mm8Ω1W speaker | [2-pack, $5.99](https://www.amazon.com/dp/B0GR48Q949) | [ElectroPeak, 1 × $0.29](https://electropeak.com/8-ohm-1w-20mm-diameter-speaker) |
| **Electronics purchase subtotal** | **$59.83** | **$25.36** |
| Power lead/switch/fastener and decoupling allowance | $10.00 unquoted | $10.00 unquoted |
| **Planning total before order charges** | **$69.83** | **$35.36** |

The item-spend difference is **$34.47**. It is not a delivered saving: outside
sourcing needs two supplier shipments, and neither delivery, tax nor any other
order fees have been quoted. The $50 delivered cap leaves **$14.64** above the
outside planning total for every such charge. Amazon already exceeds the cap.

Amazon's packages include one spare amplifier, two spare muxes and one spare
speaker. This table compares first-order cash outlay, not equal spare stock.
The parts actually consumed at Amazon pack-unit prices allocate about$48.74,
but buying those packages still costs$59.83. Treat generic alternatives as matching
component types, not identical boards: check dimensions, pins, logic/pullups,
reset access, sensor standoff and actual chip/connector variant before selection.

## Five-robot electronics arithmetic

Using the same observed package/unit prices, with no assumed bulk discount:

| Component | Amazon packages for five | Outside required units for five |
| --- | ---: | ---: |
| Sense heads | 5 × $25.99 = $129.95 | 5 × $13.90 = $69.50 |
| VL53L0X sensors | 5 five-packs = $69.95 | 25 × $1.75 = $43.75 |
| Amplifiers | 3 two-packs = $20.64 | 5 × $1.95 = $9.75 |
| Multiplexers | 2 three-packs = $13.96 | 5 × $0.47 = $2.35 |
| Speakers | 3 two-packs = $17.97 | 5 × $0.29 = $1.45 |
| **Electronics only** | **$252.47** | **$126.80** |

This is not a full five-robot quote. Five more stepper/driver pairs and unknown
quantities of WROOMs, OLEDs and power banks remain outside it, as do mechanical/
power parts, delivery, tax and any other fees. Validate one before duplication.

## Sources and price scope

Amazon prices were read from the exact product pages in the configured browser,
with variant/package titles checked. ElectroPeak prices were read from the live
HTML product-price metadata after the MCP fetch client's dependency failure;
no failing retrieval was treated as verification. Seeed's official Sense SKU
113991115 page now lists$13.90, versus the earlier$13.99 observation. No credit
card/Prime signup, coupons or cart actions were counted.

[Seeed shipping guidance](https://support.seeed.cc/portal/en/kb/articles/how-to-select-shipping-method)
calculates delivery from destination, weight and chosen service at checkout.
[ElectroPeak terms](https://electropeak.com/terms-conditions) do not give a final
shipping quote for this order and exclude applicable import charges from their
shipping description. The small first order does not qualify automatically for
advertised free-shipping thresholds. Do not substitute another similarly named
store's shipping policy.

[Machine-readable comparison](supplier-comparison.json) preserves the arithmetic.
The candidate low-item-price route is one Sense order from Seeed plus the other
four component types together from ElectroPeak, subject to fit and delivered cost.
