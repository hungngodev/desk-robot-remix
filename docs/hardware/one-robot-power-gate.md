# Protected single-cell power decision gate for one full robot

**The full robot battery and dock charger are not yet selected** because the assembled peak and continuous 5V currents have not been measured. The current `esp32_full` default now deliberately refuses to arm/energize the existing 28BYJ48/ULN2003 coils; its `DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED=0` build is an inert, sensor-capable firmware baseline, NOT an autonomous moving unit. Reuse the owned steppers for unplugged bench characterization only, or physically qualify a genuine independent fail-low stepper motor-rail cutoff before enabling them. The guarded DC alternative has a CD74HC123/DRV8833 source path, but the actual nSLEEP hardware and motor/track load remain unqualified. Neither profile is physically approved for live desk-edge motion. The XIAO Sense official wiki documents a roughly **100 mA board battery charging path**, which is not a motor power system. Do not wire the steppers, MG90S or amplifier through the XIAO's onboard battery charge output. Reference https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/ .

The active 1S concept is: one correctly rated protected Li-ion cell/pack and fuse; a 5V boost regulator rated at **low pack voltage** for the *simultaneous* WROOM, Sense, two ULN2003/28BYJ48, two servos, audio amplifier and sensor loads (including any downstream 3.3V conversion); separately qualified charging and true load-sharing path; keyed and short-protected dock contacts; own stable sensor logic supply. This is not yet a PCB schematic, so do not place an unverified battery order.

New code/scripts/power_preflight.py accepts actual observed **peak and continuous 5V amperes**, worst-case cell voltage, measured boost efficiency and optional candidate current ratings. It prints a derated output and battery current requirement. If a product only advertises a max input rating, the script will not pretend that rating is its guaranteed output.

For example, an entirely hypothetical 3A peak at 5V, a 3.0V low cell and 85 percent efficiency requires >7.6A of protected cell and boost input rating after the 30 percent margin. Therefore Pololu's U3V50F5 **5A maximum input rating** is insufficient for that *example*, even though it is marketed as a 5V power regulator. It may be adequate for a lower verified load; its actual thermal output must be checked. Vendor https://www.pololu.com/product/2565/specs .

For the selected BQ24075 (also BQ24074), TI [SLUS810N Rev N](https://www.ti.com/lit/ds/symlink/bq24075.pdf), sections 8.1 and 8.3, limits recommended BAT discharge and OUT current to 4.5 A; 5 A is an absolute maximum, not an operating rating. The integrated `screen_one_cell_power_stack` must reject a reserve-adjusted depleted-cell demand above 4.5 A even if the pack, boost and harness are rated higher. The standalone supply-sizing CLI does not select a charger. This ceiling is not proof of a carrier's thermal capacity, BAT-to-OUT voltage drop or pulse behavior.

F008/F009 remain separate physical gates: the pack-side harness requires source-proximate DC overcurrent protection, not only a fuse after the 5 V converter. Protect the dock input independently. Identify the main switch's exact disconnect scope (battery and dock are independent sources), DC voltage/current and inrush rating; it is not the independent motor cutoff. Verify each logic, actuator and audio branch against its own wiring, connector, regulator and protection ratings. Record manufacturer-required local capacitors, actual bulk capacitance, voltage rating, ESR, ripple and startup inrush; neither bulk capacitance nor aggregate load arithmetic proves rail isolation. Hold motor enable and charge authorization until the applicable measured rail, fault and recovery gates pass. No fixed capacitance or fuse SKU is selected by this arithmetic.

After actual measurement, example command:

    cd code
    uv run python scripts/power_preflight.py --peak-5v-a 3.0 --continuous-5v-a 1.8

The numbers above are **illustrative, not measurements of the user's robot**. The printed result never sets physical_load_verified or candidate_physically_qualified true. A charger with a power path and the protection/BMS are separate electrical design and physical verification tasks. Keep the charge contacts unpowered during software-only testing.

## Sense USB and signal-domain isolation

The approved power path must prevent backfeed through both supply and
signal connections. Until qualified, disconnect the inter-board signal
harness and any separately powered head peripherals before independently
powering a board for USB programming. See the
[XIAO external power and Sense SD J3 acceptance](wiring.md#xiao-external-power-and-sense-sd-j3-acceptance)
for the installed harness evidence, separate head-only/body-only tests,
and J3 continuity requirement. A supply diode alone cannot qualify GPIO
isolation. No battery, dock or actuator release follows from this check.

## Staged connector-level first-power preflight checklist

Before applying USB or battery power to Step 6 of [the build guide](../guides/build.md):

1. **Supply and USB isolation (WROOM + XIAO Sense):** Keep WROOM and XIAO USB/robot 5 V rails physically isolated until verified; never tie an external 5 V boost rail directly to XIAO USB VBUS without the manufacturer-specified Schottky diode path (`anode` on fused 5 V, `cathode` on XIAO 5 V), and keep dock charging contacts unpowered.
2. **Connector pinout, polarity, and signal direction:** Confirm every connector pin order and polarity against [the generated signal harness](one-robot-signal-harness.generated.md) and [the wiring guide](wiring.md) before mating (`GND`, `3V3`, `5V`, UART TX/RX crossover, `I2C SDA/SCL`).
3. **Rated conductor gauge, switches, and branch fuses (HOLD):** Confirm per-branch conductor gauge, fuse/disconnect rating, and local 3.3 V regulator / boost capacity on the physical harness; software arithmetic alone does not unlock actuator or pack rails (**HOLD** until measured receipts exist).
4. **Unpowered continuity and adjacent-pin short checks:** With all supplies disconnected, verify continuity end-to-end and confirm no shorts (`>100 kΩ` / open) between `GND`, `3V3`, `5V`, `VM`, and adjacent signal pins before applying logic-only 3.3 V power.
5. **STOP conditions:** Halt immediately and leave motors/charger disconnected if any continuity check fails, adjacent pins short, unknown carrier VIN/pullups expose 3.3 V pins to 5 V, or measured rails drift out of tolerance.

## Fixed rectangular 2 W speaker and 5 V amplifier power allocation

The current canonical purchase register retains MAX98357A but has already selected the **Challenge CS20-02P110-04-1X, 8 ohm 2 W, 20 x 16 x 4.7 mm** speaker candidate for the five pets. The earlier round 1 W part was rejected, and its 3.3 V mitigation must not silently override the newer fixed selection. MAX98357A VDD is allocated to a qualified, protected **5 V audio rail**; I2S input logic remains 3.3 V. Analog Devices Rev 16 lists about 1.8 W into an 8 ohm load at 5 V under specified test conditions. Neither speaker terminal connects to ground, and audio power must not bypass the XIAO USB/VBUS isolation design. This allocation does **not** prove the carrier's gain setting, actual speaker impedance, long speech thermal behavior, enclosure acoustics, microphone double talk, or supply transient margin. The printed rectangular speaker coupon is a fit reference, not a qualified sealed 1 cc acoustic chamber. Hold purchasing until exact board and physical evidence are accepted. Manufacturer sources: [MAX98357A datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf) and [Challenge speaker datasheet](https://www.challengeelectronics.com/speakers/pdf/CS20-02P110-04-1X.pdf).
