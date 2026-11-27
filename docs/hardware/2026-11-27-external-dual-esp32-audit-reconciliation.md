# External Dual-ESP32 + XiaoZhi AI Audit Reconciliation (2026-11-27)

This engineering note records transferable electrical, firmware, mechanical, and
architectural checks distilled from an external Dual-ESP32 XiaoZhi AI desk-pet
audit, explicitly reconciled against the canonical `desk-robot-remix` baseline.

> **Canonical selection & evidence invariant:** This note does **not** alter
> `docs/hardware/fleet-components.csv`, `docs/hardware/full-feature-plan.json`,
> `SOURCE_REFERENCES`, or open physical/procurement HOLD gates. Selected
> hardware remains `XIAO ESP32S3 Sense` (Head) + `ESP32-WROOM-32` (Body) +
> 8× `VL53L0X` on TCA9548A `0x70` + `0x71` accessories + protected `1S` power
> candidate path + laptop-coordinated voice/memory/vision runtime.

---

## Transferable digital, electrical, and mechanical guardrails

| Domain | Audit observation / hazard | Canonical `desk-robot-remix` posture & verification status |
| --- | --- | --- |
| Head I2S sample rate & USB/strapping safety | MAX98357A datasheet bounds sample rate and stock generic ESP32-S3 examples risk repurposing USB-OTG (`GPIO19/20`) or strapping `GPIO45`. | Canonical Head uses `XIAO ESP32S3 Sense` with isolated PDM mic (`GPIO41/42`) and `I2S` (`BCLK GPIO4`, `LRCK GPIO7`, `DOUT GPIO8`) + OLED (`SDA GPIO5`, `SCL GPIO6`) keeping native USB intact; enforced in `code/firmware/head/tests/test_sense.py` & `test_secondary_gpio_contract.py`. |
| VL53L0X (`GY-530`) 2.8 V XSHUT & input-only GPIOs | Generic `GY-530` `XSHUT` pins may lack 3.3 V protection (requiring open-drain LOW/Hi-Z control), and classic WROOM input-only `GPIO34/35/36/39` lack internal pull-ups. | Canonical Body isolates `0x29` sensors via TCA9548A `0x70` instead of 8 GPIO XSHUT lines and explicitly mandates external 3.3 V bias on `GPIO34–GPIO39` (bumper NC series & terminal IR receivers); physical breakout pullups remain **HOLD**. |
| Rear-encoded GA12-N20 length & coaxial shell width | Encoded GA12-N20 motors (~30.5 mm body + ~6 mm rear harness bend) need wider coaxial chassis clearance (~73 mm) than bare N20 units. | Primary drivetrain remains owned `28BYJ48`/`ULN2003`; guarded `N20`/`DRV8833` remains an unapproved engineering alternative requiring explicit CAD envelope & fit coupons before purchase. |
| Worst-case simultaneous power draw & brownout | Peak simultaneous track + dual-servo stall + audio + SoC + sensor transients can overload naive 1S boost/charger paths without dropout margin. | `code/scripts/power_preflight.py` screens 1S boost input under 2.9 V converter dropout (`868f6eq`); physical cell, NTC, BQ24075, and loaded rail droop remain **HOLD**. |
| Camera sensor (`OV2640` vs `OV3660`) & Head SRAM headroom | Unbounded camera + audio buffers risk Head internal SRAM exhaustion or DVP clock mismatch. | `XIAO ESP32S3 Sense` keeps single-frame `GRAB_WHEN_EMPTY` ownership and digital ESP-SR AFE reference (`SenseReferenceCodec`); physical heap/audio/camera concurrency remains **HOLD**. |
| Proactive wakeup & multi-robot echo suppression | Blind unconditioned wakeups or peer-to-peer loudspeaker chatter risk infinite acoustic feedback loops. | Canonical laptop coordinator enforces single-speaker lease (`Conversation`), hardware opt-in consent generations (`GroupContextConsent`), USB epoch/12 s freshness fencing, and local WROOM safety exclusivity. |
