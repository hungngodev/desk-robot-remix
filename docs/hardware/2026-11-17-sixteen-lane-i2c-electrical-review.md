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
This is the nominal boundary, not a universal resistor target. The preflight
accepts each pullup rail from 3.25 to 3.35 V inclusive and sums each
installed resistor's sink contribution as (max(3.3 V, measured rail V)
minus 0.4 V) / resistance. A uniform 3.35 V rail therefore requires at
least 983.3 ohms equivalent (before rounding), and mixed rails must be
summed individually. A rail below 3.3 V does not reduce the modelled
sink current. The exact 3 mA limit is checked before display rounding.

Both muxes start with all channels deselected. The upstream pullup
network alone must meet the 20 to 300 ns rise window and 3 mA sink
budget, independently of any downstream pullups. Each selected branch
must also have its own installed pullups on both SDA and SCL. With one
branch selected, the combined capacitance must not exceed 400 pF and
the combined rise and sink limits must pass again. A combined RC pass
cannot compensate for a failing upstream-only network or missing
branch pullups.

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

### RESET, address straps and brownout acceptance

Both selected muxes have active-low RESET passively pulled up to their
3.3 V supply; `BodyPins.h` sets `kMuxReset = -1`. GPIO4 is reserved by
project policy, not a silicon strapping pin. RANGE 0x70 uses A2/A1/A0
LOW; ACCESSORY 0x71 uses A2/A1 LOW and A0 HIGH. Verify the actual
breakout straps, RESET pullups and addresses with actuator power isolated.

TI SCPS207H sections 7.4.1–7.4.2 and 8.3.1 explain RESET and supply
sequencing. A valid mux reset clears its channel mask; it does not reset
the attached sensors. A WROOM-only restart need not reset either mux, and
a brief supply dip need not produce a valid mux power-on reset. The
firmware checks mux control masks and latches observed bus faults. Its
bounded clock-clear cannot isolate a permanently held downstream line
through a mux that cannot accept a write. With no driven RESET, persistent
faults require a local, motor-inhibited recovery and a verified power cycle
of the affected circuitry. A failed startup is not repaired by the normal
range polling loop. Do not treat restored SDA/SCL or a mux ACK as proof
that a sensor retained configuration or that movement can resume.

With actuator power disconnected, capture both mux VCC/RESET and upstream
SDA/SCL across cold start, WROOM-only reset, separate mux supply interruption,
and representative load-induced droop. Verify the actual supply fall,
low interval and rise against TI Figure 8-5/Table 8-1; check for unintended
back-power through signal connections. Exercise each mux with a selected
lane and with no lane selected, including a persistent SDA/SCL hold.
Record mask readbacks, sensor reacquisition, guard latch and the deliberate
local rearm after a fresh complete critical sweep. A successful host fake
or recovered bus is not proof of these electrical conditions. Keep the
physical release HOLD until the captures exist.

This script deliberately returns physically qualified FALSE even when
an illustrative RC calculation passes. The central purchasing source
requires the independent fleet receipt
sixteen_mux_channel_400khz_pullups_rise_and_sink_trials before releasing
a five robot order. This does not create more parts or excuse missing
actual generic carrier board quotations.
