# All 16 WROOM I2C lanes: source-level electrical review

The complete five robot design uses two TCA9548A multiplexers PER robot
at addresses 0x70 and 0x71, eight populated lanes on each, and a common
3.3 V WROOM GPIO21/GPIO22 upstream I2C bus. Current firmware
code/firmware/body/lib/TofBus/TofBus.cpp uses 400000 Hz.
The source explicitly deactivates the optional mux before critical range
reads. That software isolation does NOT automatically qualify each
breakout's pullups, wire capacitance, clock stretching or voltage rail.

## Manufacturer-backed source

TI [TCA9548A SCPS207H](https://www.ti.com/lit/ds/symlink/tca9548a.pdf)
section 8.2.2 and NXP [UM10204 I2C bus specification](https://www.nxp.com/docs/en/user-guide/UM10204.pdf)
require at 400 kHz Fast mode: 20 to 300 ns rise from 30% to 70%
(NXP UM10204 Rev. 7.0 Table 11), maximum
400 pF bus capacitance, and approximately 3 mA low sink with 0.4 V maximum
VOL. NXP [PN532/C1](https://www.nxp.com/docs/en/nxp/data-sheets/PN532_C1.pdf)
supports 100 and 400 kHz I2C but clock stretching remains a real risk
with the shared ESP32 Wire 15 ms timeout.

For each selected TCA9548A channel the actual WROOM upstream pullups
and active downstream pullups BOTH contribute to combined low-level sink.
The effective resistance is 1 divided by the sum of reciprocal
installed resistances. Rise time is approximated by
0.8473 times equivalent resistance times total capacitance.
At 3.3 V and 3 mA the minimum equivalent resistance is about 966.7 ohms.

| ILLUSTRATIVE 3.3 V network | Equivalent pullup | Rise at 120 pF | Current at 0.4 V LOW | On-paper result |
| --- | ---: | ---: | ---: | --- |
| Two upstream 4.7 kohm plus one selected branch 4.7 kohm | 1566.7 ohm | 159.3 ns | 1.85 mA | Pass |
| Four upstream 4.7 kohm plus one selected branch 4.7 kohm | 940 ohm | 95.6 ns | 3.09 mA | FAIL: excessive sink current |
| One 4.7 kohm upstream, none on branch | 4700 ohm | 477.9 ns | 0.62 mA | FAIL: slow Fast mode rise |

The above resistor and capacitance values are hypothetical examples,
NOT measurements of the already purchased boards. Different generic
boards can have zero, one or multiple onboard pullups. TI warns that
selected mux channels add their own pullup currents and capacitances.
Internal pass-gate on resistance and nonideal wiring make the simple
RC formula only a necessary first-order screen. Test SDA and SCL
separately on the final selected board revision.

## Full 16-lane source and trial check

Run: python code/scripts/i2c_electrical_preflight.py

It reads the live hardware plan and actual WROOM I2C clock expression,
checks both correct mux addresses, all 16 populated lanes, and rejects
conflicting target addresses within one selected lane. Without exact
installed board voltage, resistor and capacitance values, all sixteen
remain HOLD_MISSING_ELECTRICAL_VALUES.

A complete on-paper electrical model needs an upstream object and
16 independently named branches, each with separate SDA and SCL
records. The optional evidence file is passed via the --evidence flag.
For example, a partial ILLUSTRATIVE record for only one lane:

    {
      "upstream": {
        "sda": {"pullup_v": 3.3, "pullup_ohms": [4700,4700], "cap_pf": 40},
        "scl": {"pullup_v": 3.3, "pullup_ohms": [4700,4700], "cap_pf": 40}
      },
      "branches": {
        "0x70:0": {
          "sda": {"pullup_v": 3.3, "pullup_ohms": [4700], "cap_pf": 80},
          "scl": {"pullup_v": 3.3, "pullup_ohms": [4700], "cap_pf": 80}
        }
      }
    }

These are NOT vendor facts and cannot be copied as product qualification.
The physical board must be inspected for supply voltage, pullups and PCB
revision, then actual SDA/SCL rise, low level, timeout behavior and
electrical recovery must be tested with motor and speaker transients.
The purchasing receipt must include the worst measured SDA and SCL sink
currents (mA, each at most 3) and LOW voltages (V, each at most 0.4)
across the installed sixteen lanes, together with the bench fixture,
rise capture and sink capture identifiers. Use an oscilloscope with an
ammeter or calibrated shunt; a supplier shipment or an RC calculation
is not an electrical measurement. Human review must inspect the underlying
captures and their association with the actual installed boards.
Current WROOM GPIO allocation has no dedicated assured TCA RESET output:
a latched SDA-low bus may require power reset rather than software
recovery. Failing closed stops wheels, but does not make a hung mux
self-recovering.

This script deliberately returns physically qualified FALSE even when
an illustrative RC calculation passes. The central purchasing source
requires the independent fleet receipt
sixteen_mux_channel_400khz_pullups_rise_and_sink_trials before releasing
a five robot order. This does not create more parts or excuse missing
actual generic carrier board quotations.
