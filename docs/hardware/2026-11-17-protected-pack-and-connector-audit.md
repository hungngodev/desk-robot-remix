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
connectors or wires. The current provisional pack cavity in
[`remaining_fit_gauges.scad`](../cad/remixes/remaining_fit_gauges.scad)
is **86 x 35 x 14 mm**. The rendered coupon is larger because it adds
fit allowance, walls and external mounting tabs; the source packaging screen
currently reports about **107.6 x 40.6 mm** in XY for the whole tray. Those
numbers are CAD geometry only and are **not a validated final chassis**.

## Five specific product configurations, not a generic 2000mAh order

| Exact vendor variant | Protected pack dimensions | Discharge claim | Connector and wire limit | Current 86 x 35 x 14 nominal pack cavity |
| --- | --- | --- | --- | --- |
| [LiPol LP103650](https://www.lipobattery.us/3-7v-lipo-battery-lp103650-2000mah-7-4wh-with-pcm-and-wires-and-ntc-and-2510-3p/) | 51 x 36 x 10 mm | 2 A max | 2510 3P current rating not established | **NO**: 36 mm width plus clearance is wider than 35 mm |
| [LiPol LPHD7430085](https://lipo-battery.com/high-rate-discharge-lipo-battery-lphd7430085-5a-3-7v-2000mah-7-4wh/) | 86 x 30 x 7.4 mm | 5 A max | Molex 43645 0300 and 70mm attached leads require exact terminal rating | **NO**: the bare protected body fits the nominal cavity dimensions on paper, but the connector, 70 mm leads, bend radius, isolation and removal path are unmeasured, and the complete tray already conflicts with the original SMARS outer footprint |
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

## Five additional actual manufacturer variants, not silent replacements

The source catalog now contains TEN exact manufacturer configurations including
these five additional vendor models. At the same deliberately illustrative
2.55A peak cell demand and 1.53A sustained cell demand, the current 86 x 35 x
14 mm nominal cavity **still accepts none as an orderable complete assembly**.
LPHD7430085 is no longer rejected for its bare body length alone; its harness,
service clearance, electrical qualification and whole-tray chassis conflict
remain blocking.

| Exact model and manufacturer | Published protection and current | Assembled body envelope | Sourcing decision |
| --- | --- | --- | --- |
| [NX MGL00850 1S2P 6.7Ah](https://www.allbatteries.co.uk/li-ion-battery-2x-18650-1s2p-st1-3-6v-6-7ah-22awg-ntc-10k-mgl00850.html) | 10k NTC, PCM, **3.4A continuous**, 22AWG 100mm | 68.9 x 37.4 x 19.3 mm | Current on paper only for illustrative case, but no terminal ampacity, no US landed quote, too large, and 3.4A fails illustrative higher 5.1A peak |
| [VARTA 56653502013 1S2P 5.2Ah](https://resources.anglia.com/pdf/product/var/datasheets/56653502013.pdf) | 10k NTC, PCM, **2.5A continuous** despite two cells, Molex 5264 0300 | 70 x 38 x 21 mm | Fails 2.55A illustrative peak and cavity; no entire harness rating; often OEM sourcing |
| [LiTech LP1S2P2A2AL005 5.2Ah](https://litechpower.com/product/litech-power-1s2p-3-7v-5-2ah-battery-pack-lp1s2p2a2al005/) | 10k NTC, protected, **2A continuous / 3A peak** published | 66 x 39 x 20 mm | Both protection/wire and tray need qualification; 3A peak fails realistic higher stress cases |
| [BatterySpace CU JAS427 3Ah](https://www.batteryspace.com/polymer-li-ion-battery-pack-3-7v-3000mah-11-1wh-5a-rate.aspx) | 10k NTC/PCM, **5A maximum only**, 22AWG open ends | 66.5 x 37.5 x 14.5 mm with tolerance | No published separate continuous pack/terminated current, cannot claim connector rating or fit |
| [THOR 18650 1S2P 5.2Ah](https://thorbattery.com/product/thor-18650-1s2p-5200/) | Cell-level 10.4A continuous claim, included PCM with configurable current limit, optional NTC and connector selection | 65 x 37 x 18.4 mm **bare envelope only** | **NO** for the current cavity: even the bare envelope is too tall. Fit remains **UNKNOWN** for a revised tray that accepts the bare dimensions until complete assembly and lead exit are specified |

Run `code/scripts/screen_vendor_battery_harness.py` for the full ten variant
screen. The exact blob was independently copied and checked against GitHub
SHA `f2cf1b78c8acd288cc71d73bcf1213e4830d78d5`, Python compiled, and
all ten negative purchase checks were executed locally. This is a genuine
source execution, **not a full robot test**.

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
