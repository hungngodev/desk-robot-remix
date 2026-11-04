# Historical Amazon US candidates — 2026-11-03

**Superseded head procurement:** the user now reports buying the Sense shown at
**$18.87** on [AliExpress](https://www.aliexpress.us/item/3256810060131517.html).
Quantity, receipt charges and arrival are unconfirmed; do not buy another head.
The observations below remain a dated historical comparison, not a new quote.
The old remaining packages plus allowances total **$43.84**; with the reported
head purchase, cumulative spend would be **$62.71 before charges**, over the
unchanged $50 cap. The active supplier-based [parts target](parts.md) is **$40.33**
including that head, with $21.46 further parts/allowances before charges.

Sensor buying is staged: [start with two L0X samples](sensor-choice.md), at most
one five-pack for robot one, and no 25-sensor fleet purchase before mount/surface
qualification. VL53L1X is not a required upgrade. The old table's five-module
quantity represents a conditional eventual first core, not an immediate order.

## Earlier observed basket

User prefers Amazon where possible. Keep the **$50 first-prototype delivered cap**.
These are checked product-page candidates, not a completed cart or qualified
mechanical/electrical substitutions. Nothing was added to a cart or purchased.
The earlier $35.36 supplier target used a $13.90 Sense quote; it is historical
and is not the current purchased-head total or an Amazon quote.

| Candidate | Package purchase | Needed now | Observed USD |
| --- | --- | ---: | ---: |
| [XIAO ESP32S3 Sense camera/mic bundle](https://www.amazon.com/dp/B0C69FFVHH) | 1PCS, ESP32S3 Sense, observed seller Seeed Studio Official | 1 | 25.99 |
| [ACEIRMC VL53L0X, 5pcs Black](https://www.amazon.com/dp/B0F28MFW6X) | 5 modules | 5 | 13.99 |
| [MAX98357A I²S amplifiers](https://www.amazon.com/dp/B0DPJRLMDJ) | 2 modules | 1 | 6.88 |
| [TCA9548A multiplexers](https://www.amazon.com/dp/B0F8ZB8DNM) | 3 modules | 1 | 6.98 |
| [MECCANIXITY 20 mm, 8 Ω / 1 W speakers](https://www.amazon.com/dp/B0GR48Q949) | 2 speakers | 1 | 5.99 |
| **Package spend** | Includes some spares | | **59.83** |
| Existing power lead/switch/fastener allowance | Not an Amazon quote | | 8.00 |
| Existing decoupling allowance | Not an Amazon quote | | 2.00 |
| **Planning total before tax/delivery** | **Exceeds cap** | | **69.83** |

Prices were read from the live Amazon US product pages in the configured browser.
Offer, seller, availability and delivery depend on the shopper's location/time.
No coupons, Prime benefits, credit-card promotions or automatic discounts were
counted. Pack purchases are cash outlay; unused parts are not treated as refunds.
The parts physically consumed by one robot are not the same as the amount paid
for the packages.

## Head recommendation — updated after the reported purchase

Keep the **purchased Sense** as robot one's head. Its listing describes camera/mic;
verify the delivered package and actual markings. The project has a separate
compiled Sense baseline; voice interruption still requires integration/testing.
The earlier
$9.58 bare-XIAO-plus-INMP441 comparison excluded a compatible camera/add-on and
was not a complete or firmware-qualified cheaper option. Generic camera boards
might cost less, but their complete Amazon package, pins, memory, programming
and case fit still need verification before substituting them. Do not buy a
bare board expecting the camera/mic expansion to be included.

The direct Seeed $13.99 observation does not apply to this Amazon offer. The
Amazon-only candidate list already exceeds $50 before additional power parts
and order charges; preserve that conflict rather than silently increasing the
cap or dropping sensors. Buying one prototype remains the build order.

## Reuse and remaining checks

Reuse the WROOM, SSD1306, two existing stepper/driver pairs and two MG90S servos.
The user estimates about ten MG90S total. Bank model/current remain unknown and
no readable label was found. No extra microphone, OLED, Uno, Pico, Pi, N20,
DRV8833 or arm servos are in this candidate list.

The speaker listing specifies20×3.6mm with prewired1.25mm connector. New generic
ToF, mux and amplifier boards may differ from the earlier supplier modules:
verify footprints, labels, power/pullups, reset access and real sensor range.
No physical fit, power or anti-fall test has passed. The new guarded body remains
unable to arm until real sensor I/O and measured calibration are implemented.

[Machine-readable historical observations](amazon-candidates.json) preserve package counts,
links, price scope and unresolved checks. A complete delivered cart within cap
or a user-directed budget change is needed before an order-ready recommendation.
