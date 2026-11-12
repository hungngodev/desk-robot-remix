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
    for label, symbol in HEAD_SINGLE.items():
        actual = _pin(rf"#define {symbol} GPIO_NUM_(\d+)\b", head, symbol)
        if actual != bus["sense_gpio"][label]:
            raise ValueError(f"Firmware Sense pin drift: {label}")
    if bus["body_gpio"]["head_uart_rx"] != 16 or bus["sense_gpio"]["head_uart_tx"] != 2:
        raise ValueError("Unexpected XIAO to WROOM UART link")
    if bus["body_gpio"]["head_uart_tx"] != 17 or bus["sense_gpio"]["head_uart_rx"] != 1:
        raise ValueError("Unexpected WROOM to XIAO UART link")
    if "constexpr int kMuxReset = -1;" not in body:
        raise ValueError("Mux RESET must not use ESP32 strapping GPIO")
    if ("#define AUDIO_PDM_MIC_GPIO_SCK GPIO_NUM_42" not in head
            or "#define AUDIO_PDM_MIC_GPIO_DIN GPIO_NUM_41" not in head):
        raise ValueError("Stock XIAO PDM pins changed")
    if bus["sense_gpio"]["rgb_data"] != 9:
        raise ValueError("RGB reservation changed; check SD J3")
    if bus["mux_ranges"]["address"] != 0x70 or bus["mux_extras"]["address"] != 0x71:
        raise ValueError("Incorrect mux address")
    for group in ("mux_ranges", "mux_extras"):
        channels = bus[group]["channels"]
        if {c["channel"] for c in channels} != set(range(8)):
            raise ValueError(f"Incomplete {group} lanes")
        for lane in channels:
            ids = [x["address"] for x in lane["devices"]]
            if not ids or any(type(a) is not int or not 0x08 <= a <= 0x77 for a in ids):
                raise ValueError(f"Invalid {group} I2C address")
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {group} I2C address on one lane")
    ranges = bus["mux_ranges"]["channels"]
    if ranges[0]["position"] != "floor_front_left" or ranges[4]["position"] != "front_obstacle":
        raise ValueError("Critical cliff/forward sensor order drift")


def render(plan: dict, body: str, head: str) -> str:
    verify(plan, body, head)
    bus = plan["bus"]
    rows = []

    def row(source: str, target: str, signal: str, state: str = "Source allocated") -> None:
        rows.append(f"| {source} | {target} | {signal} | {state} |")

    for side in ("left", "right"):
        for phase, gpio in enumerate(bus["body_gpio"][f"{side}_stepper"], 1):
            row(f"WROOM GPIO{gpio}", f"{side} ULN2003 IN{phase}", "3.3V phase control")
    for signal, target in (("lift_servo", "MG90S lift signal"),
                           ("grip_servo", "MG90S jaw signal")):
        row(f"WROOM GPIO{bus['body_gpio'][signal]}", target, "3.3V PWM signal only")
    row("XIAO GPIO2 TX", "WROOM GPIO16 RX", "UART 115200, 3.3V")
    row("WROOM GPIO17 TX", "XIAO GPIO1 RX", "UART 115200, 3.3V")
    row("XIAO GND", "WROOM GND", "Common logic reference; power path unverified")
    row("WROOM GPIO21 SDA + GPIO22 SCL", "MPU6050 + 0x70 + 0x71 mux inputs",
        "3.3V I2C; actual breakout pullups need checking")
    for signal, target in (("head_touch", "AT42QT1010 OUT"),
                           ("bumper_nc_series", "NC bumper series OUT")):
        row(f"WROOM GPIO{bus['body_gpio'][signal]}", target,
            "3.3V input; external bias required on GPIO34 through GPIO39")
    row("MCP23017 GPB0", "optional reed switch",
        "3.3V input; closes LOW to GND", "Source polled; physically unqualified")
    row("MCP23017 GPB1", "optional PIR output",
        "3.3V input; active HIGH", "Source polled; physically unqualified")
    row("WROOM GPIO36 reserved", "left 38kHz IR demodulator",
        "Demodulated NEC burst input, external bias; ESP32 erratum",
        "No decoder or physical acceptance; do NOT wire yet")
    row("WROOM GPIO39 reserved", "right 38kHz IR demodulator",
        "Demodulated NEC burst input, external bias; ESP32 erratum",
        "No decoder or physical acceptance; do NOT wire yet")
    for signal, target in (("oled_sda", "SSD1306 SDA"), ("oled_scl", "SSD1306 SCL"),
                           ("amp_bclk", "MAX98357A BCLK"), ("amp_lrclk", "MAX98357A LRC"),
                           ("amp_din", "MAX98357A DIN")):
        row(f"XIAO GPIO{bus['sense_gpio'][signal]}", target, "3.3V head signal")
    row("XIAO onboard GPIO41 DIN + GPIO42 CLK", "Sense PDM microphone",
        "Integrated board pins, NOT connections to WROOM")
    row("XIAO GPIO9 reserved", "RGB heart data",
        "Driver not implemented; SD J3 physical conflict unresolved", "Do NOT wire yet")
    for group, mux in (("Range", bus["mux_ranges"]), ("Accessory", bus["mux_extras"])):
        for lane in mux["channels"]:
            devices = ", ".join(
                f"{d['name']} (0x{d['address']:02X})" for d in lane["devices"]
            )
            row(f"{group} TCA9548A 0x{mux['address']:02X} CH{lane['channel']} SDA/SCL",
                devices, "Isolated 3.3V I2C lane; separately qualify GND/VCC",
                "Source driver; physical carrier unqualified")
    return "\n".join([
        "# One robot: firmware checked SIGNAL harness",
        "",
        "**Not a finished protected charger or an electrically certified circuit.**",
        "Generated from docs/hardware/full-feature-plan.json and the actual",
        "BodyPins.h and head/sense/config.h symbols. Regenerate after any pin edit.",
        "Signal-only list. Never infer a power source from a logic voltage.",
        "",
        "| Source | Destination | Signal | Evidence |",
        "| --- | --- | --- | --- |", *rows, "",
        "## Unresolved connections that prevent full robot assembly", "",
        "* Matched protected 1S pack, fuse, NTC, polarity and discharge rating.",
        "* Keyed recessed dock contacts, input current limit, charger netlist,",
        "  true pack charging current and regulator peak current rating.",
        "* Qualified power and ground distribution to motors, servos, XIAO,",
        "  WROOM, speaker and 3.3V sensors. Never power actuators through MCU GPIO.",
        "* Reed/PIR now have slow MCP23017 GPIOB input source, freeing",
        "  GPIO36/39 for dual IR. The real NEC decoder, RTC/ADC erratum",
        "  filtering and final homing remain entirely unqualified.",
        "* Breakout VCC and I2C pullups, connector pin order and cable gauge.",
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
    output = render(json.loads((root / PLAN).read_text()),
                    (root / BODY_PINS).read_text(),
                    (root / HEAD_PINS).read_text())
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
