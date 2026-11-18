"""Source-contract checks for the real upstream NEC dock beacon bench sender.

This checks protocol allocation, not IR brightness, 38 kHz on an oscilloscope,
receiver/baffle aim, charger contacts, or an autonomously docked robot.
"""
import json
from pathlib import Path

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
    assert "Arduino-IRremote.git#v4.7.1" in ini
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
