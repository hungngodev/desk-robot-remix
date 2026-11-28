# BQ25895 driver reuse and electrical boundary, 2026-11-12

Scope: canonical draft PR #17 only. Research and qualification decision, not a charger selection, firmware installation, PCB validation, or battery wiring authorization. Existing dock interlocks, motion safety and power preflight remain authoritative.

## Source-checked upstream candidates

1. [PixelTheater/BQ25895-Driver](https://github.com/PixelTheater/BQ25895-Driver), README blob `aa61f4875f80400798eeff26b39b93e7c43b8dc5`, LICENSE blob `222a1a30b568ddb15ee488f22a677500be4b6dbe`. The actual LICENSE is MIT, copyright 2025 Pixel Theater. README claims Arduino/PlatformIO ESP32 support, 100 kHz I2C, Adafruit BusIO dependency, fault and ADC monitoring, and configurable charger controls. It also says most development was on Teensy and describes AI-assisted development. These are author claims, **not a verified WROOM build or tested safety implementation**. The current repository has no pinned immutable upstream commit in this note; pin and inspect the exact source before adoption. Low adoption means do not treat it as a mature, independently validated safety reference.
2. [electricimp/BQ25895](https://github.com/electricimp/BQ25895), README blob `504f8acf86470d36cff0edc7453b6e87a9b404c5`, LICENSE blob `4bcc9c2dcf133e628d297d725d22a5144115fe2e`. MIT, copyright 2019 Electric Imp. Version 3.0.0 documents asynchronous ADC conversions up to one second and battery-specific charger settings. It is written for Electric Imp Squirrel (`.nut`), **not** a drop-in ESP32 C++ driver. Useful for register sequencing, error handling and test cases, not a firmware dependency.

Manufacturer authority: [TI BQ25895 product page and Rev C datasheet](https://www.ti.com/product/BQ25895). The IC is a one-cell buck charger with NVDC SYS battery/system power-path, plus a separate selectable 4.5 to 5.5 V USB OTG boost mode rated up to 3.1 A. The 5 A **charge** figure is not a continuous 5 V robot load guarantee. SYS follows its NVDC/battery behavior; it is not an always-regulated 5 V motor/head supply. The OTG boost is not evidence that 5 V remains available while an external dock input is charging. TI's electrical and thermal limits and the selected breakout schematic, not an Arduino driver README, govern qualification.

## Decision for this robot

**Do not install either driver or enable charging.** The WROOM already has one shared I2C/safety owner and a dock monitor; introducing a second charging service or blocking bus access in its cliff loop would create an avoidable fault path. If a BQ25895 carrier is selected after electrical review, adapt only the required bounded status reads and explicit fault reporting through that owner, with MIT notice and pinned source revision. No autonomous charging approval may be inferred from I2C register reads or software tests.

Before implementation, require exact purchasable carrier schematic and revision, cell/protection/BATFET/NTC compatibility, dock contact polarity and hot insertion handling, charger input qualification, actual SYS and separately regulated rail budgets, motor/servo transient and brownout data, sustained input/output current and temperature evidence, independent fault cutoffs, and unplug/partial-contact behavior. In particular, compare any proposed carrier's documented continuous input thermal rating against the existing conservative `power_preflight.py` threshold. No fabricated current or load measurements.

## Next small independent integration

Read the latest `power_preflight.py`, its exact regression tests, and the dock monitor's existing fault states. Add a **pure offline carrier qualification fixture** that refuses to equate BQ25895 charge current, OTG output current and SYS current; test unknown carrier revision, missing continuous input rating, input loss and simultaneous charge/load claims. Keep all physical qualification flags false. Only after this test passes on exact repository source and a real carrier is selected should an upstream driver be pinned and adapted.

Evidence: GitHub connector reads of the two actual upstream README/LICENSE blobs and TI published device specifications; no source copied, no local repository tests run, no firmware built, no electrical or physical testing. Other PR #17 workers must reconcile the latest branch and comments before editing the same power files.
