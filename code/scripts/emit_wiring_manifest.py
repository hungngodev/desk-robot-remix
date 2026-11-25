"""Emit firmware-checked WROOM/XIAO wiring signals, NOT a certified power circuit.

Single source: docs/hardware/full-feature-plan.json plus actual firmware pins.
Never infer cell, charger, boost, dock terminal or actuator supply wiring.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BODY_PINS = "code/firmware/body/include/BodyPins.h"
HEAD_PINS = "code/firmware/head/sense/config.h"
PLAN = "docs/hardware/full-feature-plan.json"

BODY_SINGLE = {
    "lift_servo": "kLiftServo", "grip_servo": "kGripServo",
    "head_uart_rx": "kUartRx", "head_uart_tx": "kUartTx",
    "sda": "kSensorSda", "scl": "kSensorScl",
    "head_touch": "kTouchOutput", "bumper_nc_series": "kBumperInput",
    "terminal_ir_left_reserved": "kTerminalIrLeftInput",
    "terminal_ir_right_reserved": "kTerminalIrRightInput",
}
HEAD_SINGLE = {
    "oled_sda": "DISPLAY_SDA_PIN", "oled_scl": "DISPLAY_SCL_PIN",
    "amp_bclk": "AUDIO_I2S_SPK_GPIO_BCLK",
    "amp_lrclk": "AUDIO_I2S_SPK_GPIO_LRCK",
    "amp_din": "AUDIO_I2S_SPK_GPIO_DOUT",
    "head_uart_tx": "ROBOT_UART_TX", "head_uart_rx": "ROBOT_UART_RX",
}

# The classic ESP32 WROOM32 is not an ESP32-S3. GPIO6..11 are internal flash
# connections; 20, 24, 28..31, 37 and 38 are not usable WROOM32 module pads.
# GPIO34, 35, 36 and 39 are input-only. Outputs in this selected design must
# additionally avoid boot strapping pins and the UART0 programming console.
_WROOM32_GPIO_PADS = frozenset({
    0, 1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19,
    21, 22, 23, 25, 26, 27, 32, 33, 34, 35, 36, 39,
})
_WROOM32_SAFE_OUTPUT_PADS = frozenset({
    13, 14, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33,
})
_BODY_OUTPUT_ROLES = frozenset({
    "left_stepper", "right_stepper", "lift_servo", "grip_servo",
    "head_uart_tx", "sda", "scl",
})


def _strict_wiring_plan_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Do not allow a later pin or cliff-lane field to hide the first one."""
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate wiring plan JSON field: " + key)
        values[key] = value
    return values


def _reject_wiring_plan_constant(token: str) -> None:
    raise ValueError("Nonfinite wiring plan JSON constant: " + token)


def read_wiring_plan(path: Path) -> dict:
    """Parse the exact reviewed hardware plan without ambiguous JSON fields."""
    plan = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_wiring_plan_object,
        parse_constant=_reject_wiring_plan_constant,
    )
    if type(plan) is not dict:
        raise ValueError("Wiring plan root must be a JSON object")
    return plan


def _pin(pattern: str, source: str, label: str) -> int:
    hits = re.findall(pattern, source)
    if len(hits) != 1:
        raise ValueError(f"Missing or duplicate firmware pin: {label}")
    return int(hits[0])


def verify(plan: dict, body: str, head: str) -> None:
    """Source agreement only. Passing is NEVER electrical acceptance."""
    bus = plan["bus"]
    for owner in ("body_gpio", "sense_gpio"):
        pins = [p for value in bus[owner].values()
                for p in (value if isinstance(value, list) else [value])]
        if any(type(p) is not int or not 0 <= p <= 48 for p in pins):
            raise ValueError(f"Invalid {owner} GPIO")
        if len(pins) != len(set(pins)):
            raise ValueError(f"Double-booked {owner} GPIO")
    for label, symbol in BODY_SINGLE.items():
        actual = _pin(rf"constexpr int {symbol} = (\d+);", body, symbol)
        if actual != bus["body_gpio"][label]:
            raise ValueError(f"Firmware body pin drift: {label}")
    for label, symbol in (("left_stepper", "kLeftStepperPins"),
                          ("right_stepper", "kRightStepperPins")):
        match = re.findall(rf"constexpr int {symbol}\[\] = \{{([\d, ]+)\}};", body)
        if len(match) != 1 or [int(x) for x in match[0].split(",")] != bus["body_gpio"][label]:
            raise ValueError(f"Stepper phase pin drift: {label}")
    body_pins = bus["body_gpio"]
    if any(len(body_pins[role]) != 4 for role in ("left_stepper", "right_stepper")):
        raise ValueError("Each stepper requires exactly four phase GPIOs")
    for role, value in body_pins.items():
        pins = value if isinstance(value, list) else [value]
        if any(pin not in _WROOM32_GPIO_PADS for pin in pins):
            raise ValueError(f"WROOM32 GPIO not bonded or reserved for flash: {role}")
        if role in _BODY_OUTPUT_ROLES and any(
            pin not in _WROOM32_SAFE_OUTPUT_PADS for pin in pins
        ):
            raise ValueError(
                f"WROOM32 output GPIO input-only or boot reserved: {role}"
            )
    # Both motor backends are build-time alternatives and share GPIO pins.
    # Verify the guarded DC firmware pins as well as the older stepper map.
    for symbol, expected in (("kLeftIn1", 25), ("kLeftIn2", 26),
                             ("kRightIn1", 27), ("kRightIn2", 32)):
        if _pin(rf"constexpr int {symbol} = (\d+);", body, symbol) != expected:
            raise ValueError(f"Guarded DC motor pin drift: {symbol}")
    # The DC alternative frees GPIO23 but the STEPPER variant uses that
    # same pin as its last right ULN2003 coil. Never infer that both wires
    # can exist in the same purchased chassis harness.
    watchdog = _pin(r"constexpr int kDcHeartbeatPin = (\d+);",
                    body, "kDcHeartbeatPin")
    if (watchdog != 23 or watchdog not in bus["body_gpio"]["right_stepper"]):
        raise ValueError("DC motor watchdog must share only mutually exclusive STEP GPIO23")
    if watchdog in (25, 26, 27, 32):
        raise ValueError("DC watchdog collides with active H bridge PWM input")
    # The DC profile reuses only the stepper pins, not the sensor/servo/UART
    # roles. A synchronized STEP remap can otherwise conceal a DC collision.
    dc_pins = {25, 26, 27, 32, watchdog}
    if any(body_pins[role] in dc_pins for role in BODY_SINGLE):
        raise ValueError("DC profile GPIO collides with a nonmotor body signal")
    if set(body_pins) != set(BODY_SINGLE) | {"left_stepper", "right_stepper"}:
        raise ValueError("Unknown or incomplete body GPIO roles")
    # These arrays drive actual GPIO initialization, clearing and PWM attachment.
    # Checking only the individual declarations misses a divergent aggregate.
    motor_arrays = re.findall(r"(?m)^[ \t]*constexpr int kMotorPins\[\] = \{([^{}]+)\};", body)
    motor_pins = [[pin.strip() for pin in array.split(",")] for array in motor_arrays]
    expected_stepper = [f"{symbol}[{index}]"
                        for symbol in ("kLeftStepperPins", "kRightStepperPins")
                        for index in range(4)]
    expected_dc = ["kLeftIn1", "kLeftIn2", "kRightIn1", "kRightIn2"]
    if motor_pins != [expected_stepper, expected_dc]:
        raise ValueError("Motor initialization pin array drift")
    servo_arrays = re.findall(r"(?m)^[ \t]*constexpr int kServoPins\[\] = \{([^{}\n]+)\};", body)
    servo_pins = [[pin.strip() for pin in array.split(",")] for array in servo_arrays]
    if servo_pins != [["kLiftServo", "kGripServo"]]:
        raise ValueError("Servo initialization pin array drift")
    for label, symbol in HEAD_SINGLE.items():
        actual = _pin(rf"#define {symbol} GPIO_NUM_(\d+)\b", head, symbol)
        if actual != bus["sense_gpio"][label]:
            raise ValueError(f"Firmware Sense pin drift: {label}")
    if bus["body_gpio"]["head_uart_rx"] != 16 or bus["sense_gpio"]["head_uart_tx"] != 2:
        raise ValueError("Unexpected XIAO to WROOM UART link")
    if bus["body_gpio"]["head_uart_tx"] != 17 or bus["sense_gpio"]["head_uart_rx"] != 1:
        raise ValueError("Unexpected WROOM to XIAO UART link")
    if "constexpr int kMuxReset = -1;" not in body:
        raise ValueError("Mux RESET must remain passive; no WROOM GPIO is allocated")
    if ("#define AUDIO_PDM_MIC_GPIO_SCK GPIO_NUM_42" not in head
            or "#define AUDIO_PDM_MIC_GPIO_DIN GPIO_NUM_41" not in head):
        raise ValueError("Stock XIAO PDM pins changed")
    # The selected Sense header exposes the eight allocated signal pads.
    # Native USB, flash/PSRAM, debug UART, strapping and onboard signals
    # are not spare external harness connections.
    sense_pins = bus["sense_gpio"]
    if any(type(pin) is not int for pin in sense_pins.values()):
        raise ValueError("Sense GPIO roles require one integer pin each")
    if set(sense_pins) != set(HEAD_SINGLE) | {"rgb_data"}:
        raise ValueError("Unknown or incomplete Sense GPIO roles")
    camera_symbols = (
        *(f"CAMERA_PIN_D{i}" for i in range(8)),
        "CAMERA_PIN_XCLK", "CAMERA_PIN_PCLK", "CAMERA_PIN_VSYNC",
        "CAMERA_PIN_HREF", "CAMERA_PIN_SIOD", "CAMERA_PIN_SIOC",
    )
    fixed_head_pins = [
        _pin(rf"#define {symbol} GPIO_NUM_(\d+)\b", head, symbol)
        for symbol in (*camera_symbols, "AUDIO_PDM_MIC_GPIO_SCK",
                       "AUDIO_PDM_MIC_GPIO_DIN", "BOOT_BUTTON_GPIO")
    ]
    if (len(fixed_head_pins) != len(set(fixed_head_pins))
            or set(fixed_head_pins).intersection(sense_pins.values())):
        raise ValueError("Sense GPIO collides with onboard camera, PDM or boot signal")
    if not set(sense_pins.values()) <= {1, 2, 4, 5, 6, 7, 8, 9}:
        raise ValueError("Sense GPIO is not an allocated external header pad")
    if bus["sense_gpio"]["rgb_data"] != 9:
        raise ValueError("RGB reservation changed; check SD J3")
    # Audio power must track the CURRENT selected 8ohm 2W rectangular speaker,
    # not a retired 1W round part. The 5V MAX98357A output can be 1.8W at
    # 8ohm nominal; this contract is NOT a verified gain/thermal acceptance.
    audio = plan.get("audio_output_power_contract")
    if (not isinstance(audio, dict)
            or audio.get("amplifier_ic") != "MAX98357A"
            or type(audio.get("amplifier_vdd_v")) not in (int, float)
            or audio["amplifier_vdd_v"] != 5.0
            or type(audio.get("speaker_nominal_impedance_ohm")) is not int
            or audio["speaker_nominal_impedance_ohm"] != 8
            or type(audio.get("speaker_nominal_rating_w")) not in (int, float)
            or audio["speaker_nominal_rating_w"] != 2
            or "HOLD" not in audio.get("physical_release", "")):
        raise ValueError("Unqualified or changed 2W speaker amplifier power contract")
    # The mux inputs and IMU share the upstream bus even when every
    # downstream lane is isolated. Require the actual three firmware owners.
    upstream = bus.get("upstream")
    expected_upstream = {
        "MPU6050": {0x68, 0x69},
        "TCA9548A ranges": {0x70}, "TCA9548A interactions": {0x71},
    }
    if (not isinstance(upstream, list) or len(upstream) != len(expected_upstream)
            or any(not isinstance(device, dict)
                   or not isinstance(device.get("device"), str)
                   or type(device.get("address")) is not int for device in upstream)
            or {device["device"] for device in upstream} != expected_upstream.keys()
            or any(device["address"] not in expected_upstream[device["device"]]
                   for device in upstream)):
        raise ValueError("Upstream I2C device identity or address conflict")
    # Do not accept bool/float addresses that compare equal to an integer.
    # They would later break hex formatting or misstate the physical harness.
    for group, expected in (("mux_ranges", 0x70), ("mux_extras", 0x71)):
        address = bus[group]["address"]
        if type(address) is not int or address != expected:
            raise ValueError(f"Incorrect {group} mux address")
    for group in ("mux_ranges", "mux_extras"):
        channels = bus[group]["channels"]
        if (len(channels) != 8 or any(type(c.get("channel")) is not int for c in channels)
                or {c["channel"] for c in channels} != set(range(8))):
            raise ValueError(f"Invalid or incomplete {group} lanes")
        for lane in channels:
            ids = [x["address"] for x in lane["devices"]]
            if not ids or any(type(a) is not int or not 0x08 <= a <= 0x77 for a in ids):
                raise ValueError(f"Invalid {group} I2C address")
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {group} I2C address on one lane")
    # Dock GPIO and NFC are wired to accessory channel 5. A moved or
    # substituted expander can make a generated harness look authoritative
    # while the WROOM dock interlock reads the wrong physical device.
    dock_lane = next(c for c in bus["mux_extras"]["channels"] if c["channel"] == 5)
    if {(d.get("name"), d["address"]) for d in dock_lane["devices"]} != {
        ("PN532 I2C", 0x24), ("MCP23017", 0x20)
    } or len(dock_lane["devices"]) != 2:
        raise ValueError("Dock accessory lane 5 must retain PN532 and MCP23017")
    # Other accessory lanes also have fixed firmware owners. A valid I2C
    # address alone does not mean the driver will ever sample that device.
    # Preserve the two address straps explicitly supported by the firmware.
    interaction_roles = {
        0: {"CAP1188": {0x28, 0x29}, "MAX30102 paw pad": {0x57}},
        1: {"APDS9960": {0x39}, "AS5600 nose": {0x36}},
        2: {"ADS1115": {0x48}},
        3: {"SHT41": {0x44}, "BMP280": {0x76, 0x77}},
    }
    for channel, expected in interaction_roles.items():
        lane = next(c for c in bus["mux_extras"]["channels"] if c["channel"] == channel)
        devices = lane["devices"]
        if (len(devices) != len(expected)
                or any(not isinstance(d.get("name"), str) for d in devices)
                or {d["name"] for d in devices} != expected.keys()
                or any(d["address"] not in expected[d["name"]] for d in devices)):
            raise ValueError(f"Accessory lane {channel} sensor identity drift")
    # A haptic edge is NOT a motor supply. Preserve the selected candidate
    # CD74HC123 channel 1 pinout and protected low-side topology; the
    # independent channel 2 watchdog remains a mutually exclusive DC profile.
    # TI CD74HC123 Rev F, page 2 (pinout and truth table).
    haptic = plan.get("haptic_output_contract")
    expected_haptic = {
        "timer_ic": "CD74HC123",
        "logic_supply_v": 3.3,
        "mux_address_7bit": 113,
        "mux_channel": 5,
        "expander_address_7bit": 32,
        "trigger_gpio": "GPB2",
        "trigger_pin": 2,
        "trigger_default": "LOW",
        "input_a_pin": 1,
        "input_a_level": "LOW",
        "reset_pin": 3,
        "reset_level": "HIGH",
        "pulse_q_pin": 13,
        "inverted_q_pin": 4,
        "inverted_q_connection": "NC",
        "vcc_pin": 16,
        "gnd_pin": 8,
        "timing_cx_pin": 14,
        "timing_rxcx_pin": 15,
        "timing_resistor_to": "3V3",
        "timing_resistor_ohm": 180000,
        "timing_capacitor_nf": 1000,
        "decoupling_capacitor_nf": 100,
        "driver_ic": "AO3400",
        "driver_topology": "low_side",
        "gate_series_resistor_required": True,
        "trigger_pulldown_required": True,
        "gate_pulldown_required": True,
        "motor_nominal_v": 3,
        "motor_positive_connection": "rated_motor_supply",
        "motor_negative_connection": "mosfet_drain",
        "mosfet_source_connection": "common_ground",
        "flyback_anode_connection": "mosfet_drain",
        "flyback_cathode_connection": "motor_positive",
        "physical_qualified": False,
    }
    if (not isinstance(haptic, dict)
            or any(type(haptic.get(key)) is not type(value) or haptic[key] != value
                   for key, value in expected_haptic.items())
            or not isinstance(haptic.get("physical_release"), str)
            or not haptic["physical_release"].startswith("HOLD ")):
        raise ValueError("Unqualified or changed haptic one-shot wiring contract")
    # Battery and wheel telemetry must not be silently moved to another
    # mux lane while retaining individually valid I2C addresses. This is
    # a declared harness contract, not proof of an assembled device.
    accessory_roles = {
        4: {("INA226", 0x40), ("MAX17048", 0x36)},
        6: {("AS5600", 0x36)},
        7: {("AS5600", 0x36)},
    }
    for channel, expected in accessory_roles.items():
        lane = next(c for c in bus["mux_extras"]["channels"] if c["channel"] == channel)
        devices = lane["devices"]
        if (len(devices) != len(expected)
                or {(d.get("name"), d["address"]) for d in devices} != expected):
            raise ValueError(f"Accessory lane {channel} battery/wheel identity drift")
    voltage = plan.get("range_breakout_power_contract")
    if not isinstance(voltage, dict):
        raise ValueError("Missing cheap ToF breakout power contract")
    for key, value in (
        ("module_vin_v", 3.3), ("tca9548a_vcc_v", 3.3),
        ("upstream_pullup_target_v", 3.3),
        ("downstream_pullup_target_v", 3.3),
    ):
        if type(voltage.get(key)) not in (int, float) or voltage[key] != value:
            raise ValueError("GY-530 power voltage was changed without validation")
    if (voltage.get("selected_chip") != "VL53L0X"
            or voltage.get("generic_module_family") != "GY-530"
            or type(voltage.get("mux_address_7bit")) is not int
            or voltage["mux_address_7bit"] != 0x70
            or type(voltage.get("modules_per_robot")) is not int
            or voltage["modules_per_robot"] != 8
            or type(voltage.get("exact_vendor_pcb_verified")) is not bool
            or not isinstance(voltage.get("physical_release"), str)
            or not voltage["physical_release"].strip()):
        raise ValueError("Unapproved cheap ToF 3.3V breakout identity or release")
    ranges = bus["mux_ranges"]["channels"]
    # Each selected TCA9548A lane isolates one VL53L0X at its native
    # 7-bit address. Reject a manifest that silently substitutes another
    # device or claims multiple same-address range sensors on one lane.
    for lane in ranges:
        devices = lane["devices"]
        if (len(devices) != 1 or devices[0].get("name") != "VL53L0X"
                or devices[0]["address"] != 0x29):
            raise ValueError("Range lane must contain exactly one named VL53L0X at 0x29")
    expected_roles = (
        "floor_front_left", "floor_front_right", "floor_rear_left",
        "floor_rear_right", "front_obstacle", "left_obstacle",
        "right_obstacle", "rear_obstacle",
    )
    if any(lane["channel"] != index or lane["position"] != expected_roles[index]
           for index, lane in enumerate(ranges)):
        raise ValueError("Critical cliff/obstacle sensor channel mapping drift")


def render(plan: dict, body: str, head: str) -> str:
    verify(plan, body, head)
    bus = plan["bus"]
    rows = []

    def row(source: str, target: str, signal: str, state: str = "Source allocated") -> None:
        rows.append(f"| {source} | {target} | {signal} | {state} |")

    for side in ("left", "right"):
        for phase, gpio in enumerate(bus["body_gpio"][f"{side}_stepper"], 1):
            row(f"WROOM GPIO{gpio}", f"{side} ULN2003 IN{phase}", "3.3V phase control")
    row("WROOM GPIO25 + GPIO26", "left DRV8833 AIN1/AIN2 (DC FULL only)",
        "3.3V motor PWM signals, alternative to left ULN2003",
        "Guarded DC profile; physical load unqualified")
    row("WROOM GPIO27 + GPIO32", "right DRV8833 BIN1/BIN2 (DC FULL only)",
        "3.3V motor PWM signals, alternative to right ULN2003",
        "Guarded DC profile; physical load unqualified")
    heartbeat_phase = bus["body_gpio"]["right_stepper"].index(23) + 1
    row(f"WROOM GPIO23 (DC only; same as STEP right coil {heartbeat_phase})",
        "CD74HC123 channel 2 B rising-edge input",
        "CPU-only 15ms toggles, 3.3V; no LEDC, pull LOW at boot",
        "Source in esp32_dc_watchdog_lab and esp32_dc_integrated_lab; nSLEEP gate unqualified")
    for signal, target in (("lift_servo", "MG90S lift signal"),
                           ("grip_servo", "MG90S jaw signal")):
        row(f"WROOM GPIO{bus['body_gpio'][signal]}", target, "3.3V PWM signal only")
    row("XIAO GPIO2 TX", "WROOM GPIO16 RX", "UART 115200, 3.3V")
    row("WROOM GPIO17 TX", "XIAO GPIO1 RX", "UART 115200, 3.3V")
    row("XIAO GND", "WROOM GND", "Common logic reference; power path unverified")
    row("Recessed keyed 5V dock contacts with independent current limit",
        "BQ24075 IN pin 13 with local bypass",
        "NO permanently live exposed pogo pads; no direct battery/boost connection",
        "TI BQ24075 Rev N reference only; physical dock wiring HOLD")
    row("BQ24075 OUT pins 10/11: battery-dependent 3V to 5.6V",
        "Rated buck-boost VIN, 5V fixed regulated output",
        "Pololu S13V30F5 2.8V to 22V is voltage-range reference ONLY",
        "Actual 3V INPUT max safe current, 5V ripple and thermals HOLD")
    row("BQ24075 BAT pins 2/3, through 5mOhm >=2W Kelvin shunt",
        "Protected 1S battery PACK+ at removable rated connector",
        "INA226 IN+ on CHARGER BAT side; IN- on PACK+ side",
        "Positive current = PACK CHARGE; real thermal/PCM/wire fit UNQUALIFIED")
    row("Protected PACK- and 10k NTC lead",
        "Charger VSS and TS pin 1 respectively",
        "NTC returns to PACK-; no 10k fixed TS bypass in active charge circuit",
        "Exact NTC beta, pack pin order and thermal abort fault TEST REQUIRED")
    row("INA226 0x40 on accessory TCA9548A 0x71 CH4",
        "Kelvin sense across protected pack current shunt",
        "Opt-in signed 5mOhm current, fresh I2C seq, 3.3V logic",
        "Not physical calibration; NO software charge enable or approval")
    row("Two independent normally closed dock stop switches",
        "MCP23017 0x20 GPA0/GPA1 via 3.3V pullups",
        "Each closes to GND; open/HIGH on either input blocks motion",
        "Mandatory source interlock; actual switches and fault behavior HOLD")
    row("BQ24075 open drain PGOOD and CHG",
        "MCP23017 0x20 GPA2/GPA3 via 3.3V pullups",
        "Read-only; PGOOD=LOW input good, CHG=LOW charge indicated",
        "Indicator not battery current, status HIGH-Z when disconnected")
    row("Fused rated 5V system boost through head branch Schottky anode",
        "XIAO Sense 5V input at Schottky cathode",
        "External to head ONLY, reversed current blocked from XIAO USB",
        "Seeed official XIAO external 5V diode rule; exact diode current/heat HOLD")
    row("Fused rated 5V motor/servo branch with local >=470uF rated bulk",
        "MG90S lift/grip and motor driver VM power",
        "Direct rated 5V branch, NEVER via XIAO 3V3 or USB/diode",
        "470uF documented in cgro00 V2 servo wiring, NOT sufficient-rating proof for this robot")
    row("Fused rated 5V audio branch, independent of XIAO diode",
        "MAX98357A VIN with local 0.1uF + 10uF decoupling",
        "Common ground; amplifier outputs floating differential",
        "MAX98357A manufacturer datasheet bypass; current/acoustic tests HOLD")
    imu_address = next(device["address"] for device in bus["upstream"]
                       if device["device"] == "MPU6050")
    row(f"WROOM GPIO{bus['body_gpio']['sda']} SDA + GPIO{bus['body_gpio']['scl']} SCL",
        f"MPU6050 (0x{imu_address:02X}) + 0x70 + 0x71 mux inputs",
        "3.3V I2C; actual breakout pullups need checking")
    row("3.3V logic via appropriate pullups", "Both TCA9548A active-LOW RESET inputs",
        "Passive HIGH; no WROOM GPIO4 or other MCU RESET drive",
        "Exact breakout and startup levels HOLD")
    row("TCA9548A address straps", "0x70 ranges and 0x71 accessories",
        "0x70 A2/A1/A0 LOW; 0x71 A2/A1 LOW, A0 HIGH",
        "Verify actual board address straps before power-up")
    for signal, target in (("head_touch", "AT42QT1010 OUT"),
                           ("bumper_nc_series", "NC bumper series OUT")):
        row(f"WROOM GPIO{bus['body_gpio'][signal]}", target,
            "3.3V input; external bias required on GPIO34 through GPIO39")
    row("MCP23017 GPB0", "optional reed switch",
        "3.3V input; closes LOW to GND", "Source polled; physically unqualified")
    row("MCP23017 GPB1", "optional PIR output",
        "3.3V input; active HIGH", "Source polled; physically unqualified")
    row("DRV8833 nFAULT (DC only)", "MCP23017 GPB3",
        "Open drain active LOW; 4.7k 3.3V pullup at driver, 100k pulldown at expander",
        "Disconnected lead must read LOW/fault; carrier and fault response HOLD")
    row("MCP23017 GPB2", "CD74HC123 rising-edge haptic trigger (1B pin 2)",
        "3.3V lab-only edge, not motor current; external defined LOW at boot",
        "Source gated in esp32_full_haptic_lab and esp32_dc_integrated_lab; physical one-shot NOT qualified")
    row("Regulated 3.3V logic rail", "CD74HC123 VCC pin 16",
        "100nF local bypass to ground; HC not HCT",
        "Haptic bench candidate only")
    row("Common logic and motor return", "CD74HC123 GND pin 8 and AO3400 source",
        "Shared reference; motor current stays off logic signal wires",
        "Haptic bench candidate only")
    row("Logic LOW / HIGH", "CD74HC123 1A pin 1 LOW / 1CLR pin 3 HIGH",
        "GPB2 externally pulled LOW; verify startup and reset",
        "Haptic bench candidate only")
    row("180kOhm timing resistor to 3.3V", "CD74HC123 1RxCx pin 15",
        "1uF candidate capacitor between pin 15 and 1Cx pin 14",
        "Timing at actual 3.3V NOT measured")
    row("CD74HC123 1Q pin 13", "AO3400 gate through series resistor",
        "External gate pulldown; inverted Q pin 4 unused",
        "Haptic bench candidate only")
    row("Rated regulated 3V motor supply", "Coin motor positive; motor negative to AO3400 drain",
        "Flyback diode cathode to motor positive, anode to drain",
        "Current limit, stall, heat and independent pulse termination HOLD")
    row(f"WROOM GPIO{bus['body_gpio']['terminal_ir_left_reserved']} reserved",
        "left 38kHz IR demodulator",
        "Demodulated NEC burst input, external bias; ESP32 erratum",
        "Bounded RMT decoder in source; NO physical receiver acceptance, do NOT wire yet")
    row(f"WROOM GPIO{bus['body_gpio']['terminal_ir_right_reserved']} reserved",
        "right 38kHz IR demodulator",
        "Demodulated NEC burst input, external bias; ESP32 erratum",
        "Bounded RMT decoder in source; NO physical receiver acceptance, do NOT wire yet")
    for signal, target in (("oled_sda", "SSD1306 SDA"), ("oled_scl", "SSD1306 SCL"),
                           ("amp_bclk", "MAX98357A BCLK"), ("amp_lrclk", "MAX98357A LRC"),
                           ("amp_din", "MAX98357A DIN")):
        row(f"XIAO GPIO{bus['sense_gpio'][signal]}", target, "3.3V head signal")
    row("Rated, isolated 5V audio power rail", "MAX98357A VDD/VIN",
        "5V for current 2W speaker; never parallel unisolated USB VBUS",
        "Design allocation only; audio rail peaks, clipping and heat HOLD")
    row("MAX98357A OUTP and OUTN", "8 ohm 2 W CS20-02P110-04-1X + and -",
        "Bridge tied differential outputs; NEVER connect either output to GND",
        "Manufacturer 5V 8ohm nominal 1.8W; real carrier/rectangular baffle heat HOLD")
    row("XIAO Sense onboard camera", "Internal camera data, clocks and SCCB",
        "Stock integrated camera; no external harness connection",
        "Source allocation only; physical camera and SD isolation HOLD")
    row("XIAO onboard GPIO41 DIN + GPIO42 CLK", "Sense PDM microphone",
        "Integrated board pins, NOT connections to WROOM")
    row("XIAO GPIO9 reserved", "RGB heart data",
        "Xiaozhi WS2812 driver compiled only with explicit opt-in; SD J3 and 5V level buffer still unqualified", "Do NOT wire yet")
    row("Rated regulated 3.3V expansion rail",
        "eight GY-530 VL53L0X VIN pins and TCA9548A 0x70 VCC",
        "3.3V ONLY in selected design; 5V VIN can raise SDA/SCL to 5V",
        "Exact seller board pullup and every upstream/downstream HIGH rail UNTESTED")
    for group, mux in (("Range", bus["mux_ranges"]), ("Accessory", bus["mux_extras"])):
        for lane in mux["channels"]:
            devices = ", ".join(
                f"{d['name']} (0x{d['address']:02X})" for d in lane["devices"]
            )
            # The selected low-cost VL53L0X carrier may pull external
            # SDA/SCL HIGH toward its VIN. A 5V VIN is not a 3.3V-safe
            # WROOM/mux connection just because the sensor carrier powers on.
            # This is a hard assembly hold, never a measured voltage claim.
            if group == "Range":
                signal = ("WROOM 3.3V logic ONLY; carrier VIN and external "
                          "SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden")
                position = lane["position"].replace("_", " ")
                if lane["channel"] < 4:
                    role = "critical cliff"
                elif lane["channel"] == 4:
                    role = "critical obstacle"
                else:
                    role = "read-only observation; no movement authority"
                devices = f"{devices}, {position} ({role})"
                evidence = "Unqualified carrier; DO NOT ENERGIZE before voltage checks"
            else:
                if lane["channel"] in (6, 7):
                    side = "left" if lane["channel"] == 6 else "right"
                    devices = f"{devices}, {side} wheel rotation"
                signal = "Isolated 3.3V I2C lane; separately qualify GND/VCC"
                evidence = "Source driver; physical carrier unqualified"
            row(f"{group} TCA9548A 0x{mux['address']:02X} CH{lane['channel']} SDA/SCL",
                devices, signal, evidence)
    return "\n".join([
        "# One robot: firmware checked SIGNAL harness",
        "",
        "**Not a finished protected charger or an electrically certified circuit.**",
        "Generated from docs/hardware/full-feature-plan.json and the actual",
        "BodyPins.h and head/sense/config.h symbols. Regenerate after any pin edit.",
        "Signal-only list. Never infer a power source from a logic voltage.",
        "",
        "**Motor variants are mutually exclusive:** `esp32_full` uses ULN2003 steppers;",
        "`esp32_dc_full` uses DRV8833 DC motors. Never connect both motor drivers.",
        "",
        "| Source | Destination | Signal | Evidence |",
        "| --- | --- | --- | --- |", *rows, "",
        "## Unresolved connections that prevent full robot assembly", "",
        "* Matched protected 1S pack, fuse, NTC, polarity and discharge rating.",
        "* Keyed recessed dock contacts, input current limit, charger netlist,",
        "  true pack charging current and regulator peak current rating.",
        "* Qualified power and ground distribution to motors, servos, XIAO,",
        "  WROOM, speaker and 3.3V sensors. Never power actuators through MCU GPIO.",
        "* Source-reused XIAO power isolation: Seeed 5V external input needs",
        "  Schottky anode on fused boost and cathode on XIAO 5V pin.",
        "  cgro00/desk-robot V2 docs use 1N5817 + 470uF 5V servo bulk;",
        "  its two-servo supply rating is NOT sufficient evidence for our motors.",
        "* XIAO external 5V/VBUS requires manufacturer-compliant diode or",
        "  verified power-path isolation from USB before simultaneous USB use.",
        "  NEVER directly tie robot boost 5V to laptop USB VBUS.",
        "* XIAO Sense camera/SD expansion J3 must be physically isolated",
        "  and continuity-checked before GPIO7/8 I2S and GPIO9 RGB use.",
        "  SD card slot disabled and empty; verify shipped PCB revision.",
        "* DC-only GPIO23 heartbeat is NOT the DRV8833 motor driver nSLEEP.",
        "  It needs the independent second HC123 channel, verified Q timeout",
        "  and a fail-LOW interface against any onboard VM-to-nSLEEP pullup.",
        "* Haptic MCP23017 GPB2 drives only a generic HC123 one-shot trigger,",
        "  not the coin motor. Verify active-HIGH edge, 3.3V rail, timed Q and",
        "  low-side MOSFET/flyback current; production effect stays disabled.",
        "* Reed/PIR now have slow MCP23017 GPIOB input source, freeing",
        "  GPIO36/39 for dual IR. Real timing, optical baffles, RTC/ADC erratum",
        "  filtering and final homing remain entirely unqualified.",
        "* Breakout VCC and I2C pullups, connector pin order and cable gauge.",
        "* All eight VL53L0X carriers: identify PCB revision and verify VIN",
        "  plus upstream/downstream SDA/SCL HIGH voltages with motors OFF.",
        "  Do NOT energize any ToF lane until 5V WROOM exposure is excluded.",
        "* Printed fit, local cliff geometry, audio and charger bench trials.",
        "",
        "**Assembly readiness: NO. Firmware signal allocation only.**",
        ""
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, help="Write generated Markdown here")
    args = parser.parse_args()
    root = args.root
    output = render(read_wiring_plan(root / PLAN),
                    (root / BODY_PINS).read_text(),
                    (root / HEAD_PINS).read_text())
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
