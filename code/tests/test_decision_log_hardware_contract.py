"""Keep active architecture decisions aligned with source, not physical acceptance."""
from pathlib import Path
from runpy import run_path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def decision(prefix: str) -> str:
    rows = [line for line in read("docs/decision-log.md").splitlines() if line.startswith(prefix)]
    assert len(rows) == 1
    return rows[0]


def test_selected_range_mux_is_not_the_accessory_mux():
    row = decision("| Edge sensing ")
    driver = read("code/firmware/body/lib/TofBus/TofBus.h")
    assert "kMuxAddress = 0x70" in driver
    assert "kRangeCount = 5 + (DESK_ROBOT_EXTRA_RANGERS ? 3 : 0)" in driver
    assert "8 generic VL53L0X GY-530" in row
    assert "`0x70` lanes 0–7" in row
    assert "separate `0x71` mux is for accessories" in row
    assert "still require physical qualification" in row


def test_audio_decisions_preserve_the_existing_owner_and_reference():
    row = decision("| D06 ")
    pins = read("code/firmware/head/sense/config.h")
    codec = read("code/firmware/head/sense/sense_reference_codec.h")
    native = read("code/laptop/server/overlay/desk_robot_native_omni.py")
    assert "AUDIO_OUTPUT_SAMPLE_RATE 32000" in pins
    assert "AUDIO_INPUT_SAMPLE_RATE 16000" in pins
    assert "kSpeakerRate = 32000" in codec
    assert "kMicRate = 16000" in codec
    assert "32 kHz MAX98357A I2S" in row
    assert "16 kHz PDM" in row
    assert "audible stop remain unqualified" in row
    assert "own the physical microphone and speaker" in native
    assert "sole physical microphone/speaker transport" in decision("| D08 ")


def test_dc_coast_is_not_braking_or_qualified_cutoff():
    row = decision("| D13 ")
    main = read("code/firmware/body/src/main.cpp")
    ini = read("code/firmware/body/platformio.ini")
    assert "ledcWrite(channel, 0)" in main
    assert "-DDESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED=0" in ini
    assert "LOW/LOW coast" in row
    assert "not active braking or proof of physical stopping" in row
    assert "cutoff and loaded stop remain unqualified" in row


def test_procurement_decision_preserves_budget_and_owned_exception():
    assert decision("| Procurement policy ") == (
        "| Procurement policy (current) | No new Adafruit hardware purchases. "
        "Reported owned hardware may be reused only after qualification; "
        "driver references are not purchases. The $50 first-unit delivered cap "
        "includes prior spending, shipping, tax, its dock and the shared station. |"
    )
    policy = run_path(str(ROOT / "code/scripts/procurement_policy.py"))
    blocked = policy["adafruit_new_hardware"]
    assert blocked({"brand": "Adafruit"}, 1) is True
    assert blocked({"brand": "Adafruit"}, 0) is False
    assert blocked({"brand": "Generic"}, 1) is False
    assert "PROTOTYPE_CAP_CENTS = 5000" in read("code/scripts/landed_cost.py").splitlines()


def test_voice_decision_preserves_priority_and_acoustic_gate():
    assert decision("| Voice priority ") == (
        "| Voice priority (current) | Xiaozhi and the XIAO ESP32S3 Sense retain "
        "one physical microphone/speaker path. P0 physical fault > P1 human VAD > "
        "P2 current tool completion > P3 optional initiative. A2 requires 19/20 "
        "audible stops within 500 ms; physical qualification remains HOLD. |"
    )
    source = " ".join(read("docs/source-map.md").split())
    assert "P0 physical fault > P1 human VAD > P2 current tool completion > P3" in source
    pins = read("code/firmware/head/sense/config.h").splitlines()
    for pin in (
        "AUDIO_PDM_MIC_GPIO_SCK GPIO_NUM_42",
        "AUDIO_PDM_MIC_GPIO_DIN GPIO_NUM_41",
        "AUDIO_I2S_SPK_GPIO_BCLK GPIO_NUM_4",
        "AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_7",
        "AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_8",
    ):
        assert f"#define {pin}" in pins


def decision_fields(prefix: str) -> tuple[str, str]:
    fields = decision(prefix).strip("|").split("|")
    assert len(fields) == 3, prefix
    return fields[1].strip(), fields[2].strip()


def test_recent_range_decisions_keep_selection_frozen_and_lanes_allocated():
    evidence, action = decision_fields("| D03 ")
    assert "8 generic VL53L0X (GY-530, `0x29`) on `0x70` lanes 0–7" in evidence
    assert (
        "four corner floor roles, one front obstacle, three left/right/rear diagnostics"
        in evidence
    )
    assert "loaded stopping margin remain unqualified" in evidence
    assert "without reopening sensor selection or evaluating VL53L4CD" in action
    assert "before live edge motion" in action

    evidence, action = decision_fields("| D04 ")
    assert "left/right/rear read-only diagnostics on lanes 5–7" in evidence
    assert "`0x71` accessory lanes 0–7" in evidence
    assert "Reject Sense 41/42 heartbeat wiring." in action
    assert "Physical electrical qualification remains HOLD." in action


def test_audio_decision_columns_and_acceptance_ledger_agree():
    evidence, action = decision_fields("| D06 ")
    assert "32 kHz MAX98357A I2S (BCLK GPIO4, LRCK GPIO7, DOUT GPIO8)" in evidence
    assert "16 kHz PDM (clock GPIO42, data GPIO41)" in evidence
    assert "audible stop remain unqualified" in evidence
    assert "Required gate 19/20 ≤500ms and 18/20 correct new requests" in action
    assert "zero echo-only interruptions 10min" in action

    evidence, action = decision_fields("| D08 ")
    assert "sole physical microphone/speaker transport and tool route" in evidence
    assert "not through a second audio pipe" in evidence
    assert "Preserve the **single audio/turn owner**" in action

    rows = [
        line for line in read("docs/records/verification.md").splitlines()
        if line.startswith("| **A2 Audio/quiet** |")
    ]
    assert len(rows) == 1
    criteria = rows[0].split("|")[2]
    assert "**At least 19/20** trials visibly/audibly stop TTS in **<=500ms**" in criteria
    assert "**18/20** recover intelligible *new* request" in criteria
    assert "**zero false self-interruptions**" in criteria
