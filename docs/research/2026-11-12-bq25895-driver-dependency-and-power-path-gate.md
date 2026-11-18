# BQ25895 reuse and power path gate

Research 2026-11-12. Source review only, not hardware qualification.

Sources: TI datasheet https://www.ti.com/product/BQ25895 and MIT licensed https://github.com/PixelTheater/BQ25895-Driver .

The PixelTheater driver advertises ESP32 and PlatformIO, but its examples require Adafruit_I2CDevice and Adafruit BusIO. Development was mainly on Teensy. Its README describes a hobbyist library; its repository currently has nine commits and zero stars. Do not claim this driver is widely proven, dependency free or tested on this WROOM. Pin an exact upstream revision, preserve MIT notices and verify shared I2C bus ownership before any code import.

TI distinguishes buck charging up to 5 A, USB OTG boost up to 3.1 A and NVDC SYS power path. SYS is not a guaranteed regulated 5 V motor rail, and OTG boost does not establish simultaneous charging plus boosted output. Input DPM can reduce charge current and cause battery supplement. Carrier revision, thermistor, input protection, load sharing, cell protection, thermal behavior and charge contact isolation remain independent gates.

Decision: do not install this driver or energize dock contacts. Preserve existing power_preflight.py and motion/charge fences. Next source task: inspect exact current power preflight and tests; add a fail closed carrier specific operating mode qualification check with a deterministic negative test, rather than equating headline IC ratings with a carrier continuous current rating. Next physical task: bench measure a selected protected 1S carrier with motors inhibited. No tests or hardware measurements were executed for this note.
