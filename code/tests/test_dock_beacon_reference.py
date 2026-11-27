"""Source-contract checks for the real upstream NEC dock beacon bench sender.

This checks protocol allocation, not IR brightness, 38 kHz on an oscilloscope,
receiver/baffle aim, charger contacts, or an autonomously docked robot.
"""
import csv
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/hardware/full-feature-plan.json"
BEACON = ROOT / "code/firmware/dock/src/main.cpp"
PLATFORMIO = ROOT / "code/firmware/dock/platformio.ini"
NEC = ROOT / "code/firmware/body/lib/TerminalIr/NecBurst.h"


def test_per_dock_beacon_and_dual_receiver_are_counted():
    p = json.loads(PLAN.read_text())
    parts = {x["id"]: x for x in p["parts"]}
    assert p["target_robots"] == 5
    assert parts["dock_ir_receivers"]["per_robot"] == 2
    assert parts["dock_ir_beacon_controller"]["per_robot"] == 1
    assert parts["dock_ir_emitter_channels"]["per_robot"] == 2
    assert "SAME classic NEC frame" in parts["dock_ir_emitter_channels"]["notes"]
    assert not p["qualified_assumptions"] and p["physical_trial_count"] == 0


def test_dock_ir_purchase_references_match_cad_and_charging_guide():
    plan = json.loads(PLAN.read_text())
    parts = {part["id"]: part for part in plan["parts"]}
    with (PLAN.parent / "fleet-components.csv").open(newline="") as stream:
        fleet = {row["part_id"]: row for row in csv.DictReader(stream)}
    shopping = (PLAN.parent / "complete-shopping-checklist.md").read_text()
    charging = (PLAN.parent / "charging-design-and-validation.md").read_text()
    cad = (ROOT / "docs/cad/remixes/dock/README.md").read_text()
    procurement = (ROOT / "code/scripts/procurement_release.py").read_text()

    for role, quantity in (
        ("dock_ir_receivers", 2),
        ("dock_ir_beacon_controller", 1),
        ("dock_ir_emitter_channels", 2),
    ):
        part = parts[role]
        row = fleet[role]
        assert part["per_robot"] == quantity == int(row["per_robot"])
        assert int(row["fleet_total"]) == quantity * plan["target_robots"]
        assert row["component"] == part["name"]
        assert row["purchase_approved"] == "NO"
        assert part["name"] in shopping

    assert "TSOP38438" in parts["dock_ir_receivers"]["name"]
    for document in (charging, cad, procurement):
        assert "TSOP38438" in document
        assert "TSAL6200" in document
    assert "bare LED" in charging
    assert "5.5 mm bore is a clearance test only" in cad
    assert "sample_is_complete_functional_channel" in procurement
    linked = {item["id"]: item for item in plan["linked_subassemblies"]}
    drivers = linked["dock_ir_transistor_channels"]
    assert drivers["parent_role"] == "dock_ir_emitter_channels"
    assert drivers["fleet_quantity"] == 2 * plan["target_robots"]
    assert drivers["disposition"] == "unresolved"


def test_five_distinct_classic_nec_beacons_match_decoder_contract():
    source = BEACON.read_text()
    decoder = NEC.read_text()
    ini = PLATFORMIO.read_text()
    assert "#define IR_SEND_PIN 3" in source
    assert "#include <IRremote.hpp>" in source
    assert "IrSender.sendNEC(kAddress, kCommand, 0);" in source
    assert "constexpr uint8_t kAddress = 0x12;" in source
    assert "0x30 + DESK_ROBOT_DOCK_ID" in source
    assert "#define USE_NO_SEND_PWM" not in source
    assert "decode_nec" in decoder and "count != 34" in decoder
    assert "address ^ address_inverse" in decoder
    assert "command ^ command_inverse" in decoder
    assert "motor_authorized = false" in decoder
    assert "charging_authorized = false" in decoder
    assert "Arduino-IRremote.git#498dc591b255d8ba2e239c875804bdab2ab0fe91" in ini
    assert "board = nanoatmega328" in ini
    codes = set()
    for dock_id in range(1, 6):
        assert f"-DDESK_ROBOT_DOCK_ID={dock_id}" in ini
        address = 0x12
        command = 0x30 + dock_id
        frame = (address | ((address ^ 0xFF) << 8)
                 | (command << 16) | ((command ^ 0xFF) << 24))
        assert ((frame & 0xFF) ^ ((frame >> 8) & 0xFF)) == 0xFF
        assert (((frame >> 16) & 0xFF) ^ ((frame >> 24) & 0xFF)) == 0xFF
        assert frame not in codes
        codes.add(frame)
    assert len(codes) == 5


@pytest.mark.parametrize("dock_id", range(1, 6))
def test_beacon_quiet_gap_and_rollover(tmp_path, dock_id):
    """Compile the real loop with a fake clock and synchronous sender."""
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ required for dock scheduler host test")
    (tmp_path / "Arduino.h").write_text('''#pragma once
#include <stdint.h>
#include <cassert>
constexpr int LOW = 0, OUTPUT = 1;
extern uint32_t clock_ms;
extern int writes;
inline uint32_t millis() { return clock_ms; }
inline void digitalWrite(int pin, int value) {
  assert(pin == 3 && value == LOW); ++writes;
}
inline void pinMode(int pin, int mode) { assert(pin == 3 && mode == OUTPUT); }
inline void delay(unsigned) { assert(false && "blocking idle delay"); }
''')
    (tmp_path / "IRremote.hpp").write_text('''#pragma once
static_assert(IR_SEND_DUTY_CYCLE_PERCENT == 30);
struct Sender {
  int calls = 0;
  void sendNEC(int address, int command, int repeats) {
    assert(address == 0x12 && command == 0x30 + DESK_ROBOT_DOCK_ID);
    assert(repeats == 0);
    ++calls;
    clock_ms += 68;
  }
};
inline Sender IrSender;
''')
    harness = tmp_path / "harness.cpp"
    harness.write_text('''#include <Arduino.h>
uint32_t clock_ms = 0xffffff80U;
int writes = 0;
#include "main.cpp"
int main() {
  setup();
  assert(writes == 1);
  loop();
  assert(IrSender.calls == 1 && writes == 2);
  const auto end = clock_ms;
  clock_ms = end + 79U;  // wraps the fake 32-bit millis clock
  loop();
  assert(IrSender.calls == 1);
  clock_ms = end + 80U;
  loop();
  assert(IrSender.calls == 2 && writes == 3);
  clock_ms += 10000U;  // overdue: one burst, no catch-up train
  loop();
  loop();
  assert(IrSender.calls == 3 && writes == 4);
}
''')
    binary = tmp_path / "beacon"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         f"-DDESK_ROBOT_DOCK_ID={dock_id}", "-I", str(tmp_path),
         "-I", str(BEACON.parent), str(harness), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
