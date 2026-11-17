# Protected 1S battery harness: manufacturer variants and real disqualifiers

**Purchasing status: HOLD.** No one manufacturer candidate here is verified
safe for the entire desk pet, and no parts order is authorized. This audit
addresses the actual **battery cell plus PCM plus NTC plus connector plus leads
plus enclosure**. It is not a second BOM. The single primary role remains
`cap_power`, with `protected_ntc_pack` as its linked exact assembly decision.

The source-of-truth load calculation remains
[`code/scripts/power_preflight.py`](../../code/scripts/power_preflight.py).
The new [vendor harness screener](../../code/scripts/screen_vendor_battery_harness.py)
reuses its conservative input demand and separately rejects undersized
connectors or wires. The standard envelope in
[`remaining_fit_gauges.scad`](../cad/remixes/remaining_fit_gauges.scad)
is 68 x 35 x 14 mm and is **not a validated final chassis**.

## Five specific product configurations, not a generic 2000mAh order

| Exact vendor variant | Protected pack dimensions | Discharge claim | Connector and wire limit | Current 68 x 35 x 14 nominal tray |
| --- | --- | --- | --- | --- |
| [LiPol LP103650](https://www.lipobattery.us/3-7v-lipo-battery-lp103650-2000mah-7-4wh-with-pcm-and-wires-and-ntc-and-2510-3p/) | 51 x 36 x 10 mm | 2 A max | 2510 3P current rating not established | **NO**: 36 mm width plus clearance is wider than 35 mm |
| [LiPol LPHD7430085](https://lipo-battery.com/high-rate-discharge-lipo-battery-lphd7430085-5a-3-7v-2000mah-7-4wh/) | 86 x 30 x 7.4 mm | 5 A max | Molex 43645 0300 and 70mm attached leads require exact terminal rating | **NO**: length 86 mm before wire relief exceeds 68 mm |
| [BatterySpace PR CU R512, 22AWG open leads](https://www.batteryspace.com/custom-polymer-li-ion-battery-3-7v-2000mah-7-4-wh-4a-rate-with-10k-thermistor.aspx) | 68 x 50 x 7 mm | 4 A max | Supplier states 4 A for **22 AWG open leads**, no safe connector/harness selection yet | **NO**: 50 mm width and unqualified lead termination |
| [BatterySpace PR CU R512, Molex 26AWG](https://www.batteryspace.com/custom-polymer-li-ion-battery-3-7v-2000mah-7-4-wh-4a-rate-with-10k-thermistor.aspx) | 68 x 50 x 7 mm | 4 A cell claim | **2.2 A connector and leads** published | **NO**: both 50 mm width and connector rating may fail |
| [BatterySpace PR CU R512, JST SHR 30AWG](https://www.batteryspace.com/custom-polymer-li-ion-battery-3-7v-2000mah-7-4-wh-4a-rate-with-10k-thermistor.aspx) | 68 x 50 x 7 mm | 4 A cell claim | **0.86 A connector and leads** published | **NO**: both 50 mm width and insufficient cable |

All values above are manufacturer website claims, not independent measurements.
A published **maximum discharge** is not by itself a verified continuous
current rating at the actual operating temperature and connector. The source
screen therefore treats continuous pack capability as unknown, rather than
converting these manufacturers' maximum ratings to a guaranteed sustained
current.
None establishes the final polarity or a mounted charger connection. A 4 A
cell rating does **not** override 2.2 A or 0.86 A harness ratings.

## Bounded illustrative load calculation, not a measured robot current

Using the preexisting power sizing formula with **hypothetical** 5 V peak
load 1.0 A, sustained load 0.6 A, minimum cell 3.0 V, boost efficiency 85%
and margin 1.3:

* Required peak protected-cell input = ceil(5 x 1.0 x 1.3 / (3 x 0.85))
  = **2.550 A**.
* Required continuous input = ceil(5 x 0.6 x 1.3 / (3 x 0.85))
  = **1.530 A**.

Under just this illustrative 1 A peak load, 2 A LP103650 is already below the
computed required peak. BatterySpace's 2.2 A and 0.86 A assembled connector
variants are also below 2.55 A even when their cell's **published maximum**
is 4 A. LPHD7430085's published 5 A maximum exceeds this *hypothetical peak*,
but the continuous thermal/current rating of the assembled pack is **not
separately established**; its length and unqualified harness also block it.
**Do not treat the illustrative current as a measured motor, audio or radio
load. The actual peaks could be higher.**

With a hypothetical **2.0 A** 5 V peak, the same conservative formula demands
**5.099 A** from the protected 1S supply, exceeding even the advertised 5 A
battery candidate. Thus 5 A is not a guarantee, and the correct next decision
must use the actual peak (simultaneous two motor drive, servo stall, camera,
radio, speaker) instead of assuming 2000 mAh means high power.

## Rules for an orderable exact battery assembly

1. Select and document the **exact assembled pack SKU**, including PCM,
   connector housing, crimp contacts, 3 wire polarity order and 10 k NTC
   type/temperature curve. Do not assume two three-pin connectors are keyed
   alike or rated alike.
2. The chosen charger board's actual TS/THERM circuit must monitor the
   assembled pack's NTC. TI [BQ24074](https://www.ti.com/product/BQ24074)
   provides a real TS pin; SparkFun PRT 13777's fixed 10 k bypass does not
   establish pack NTC monitoring without a physically reviewed modification.
   Avoid selecting a second BQ27441 plus MAX17048 fuel gauge.
3. Use actual **verified connector and wire ampacity** for peak/continuous
   design, never only the cell or PCM current. The one robot supply must be
   sized against the *lowest* rating in that chain at minimum battery voltage.
4. Fit the **entire wired and protected** battery plus strain relief, fuse,
   switch and boost/charger PCB with isolation, removable service path and
   sufficient printed structure. Do not merely rescale the 68 mm fit coupon
   and label it the complete robot.
5. Test one actual candidate under a current-limited supply and verify
   protected-pack temperature, fresh fault monitoring, charger thermal and
   termination behavior, dock contact loss, actual signed battery current,
   brownout, and hot contact wiring. Five-fold purchase only after these pass.

**No vendor product above is an approval to buy.** A fully populated
`code/scripts/procurement_release.py` receipt set must confirm both this
electrical/mechanical chain and every other one-robot feature before a
fleet-wide order can be approved.
