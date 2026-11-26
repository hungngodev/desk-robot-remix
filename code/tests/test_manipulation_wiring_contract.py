"""Keep the operator harness aligned with the body manipulation owners."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "code/firmware/body"
WIRING = ROOT / "docs/hardware/wiring.md"


def test_servo_pwm_owners_match_operator_harness():
    pins = (FW / "include/BodyPins.h").read_text()
    pulse = (FW / "include/ServoPulse.h").read_text()
    main = (FW / "src/main.cpp").read_text()
    for declaration in (
        "kLiftServo = 18;", "kGripServo = 19;", "kServoChannels[] = {4, 5};",
        "kServoFrequency = 50;", "kServoResolution = 16;",
    ):
        assert declaration in pins
    assert "65535UL / 20000UL" in pulse
    for index, name, state in ((0, "Lift", "lift"), (1, "Grip", "grip")):
        channel = f"body_pins::kServoChannels[{index}]"
        assert f"ledcAttachPin(body_pins::k{name}Servo, {channel});" in main
        assert main.count(f"ledcWrite({channel}, servo_duty(state.{state}));") == 2
    assert "GPIO18 / LEDC4 lift, GPIO19 / LEDC5 jaw; both 50 Hz, 16 bit" in WIRING.read_text()


def test_force_adc_channel_owners_match_operator_harness():
    source = (FW / "lib/AccessorySensors/AccessorySensors.cpp").read_text()
    grasp = (ROOT / "code/laptop/src/desk_robot/grasp_feedback.py").read_text()
    calibration = (ROOT / "code/scripts/calibrate_jaw_fsr.py").read_text()
    assert "verified_mux(0x71, static_cast<std::uint8_t>(1U << lane))" in source
    assert "case 2: force(now_ms); break;" in source
    assert "ads_channel_ == 0 ? 0xC383U : 0xD383U" in source
    assert "read16(0x48, 0x00, value)" in source
    assert "return group[\"adc\"][1], group[\"jaw_seq\"]" in grasp
    assert "AIN1/GND (ADS1115 config 0xD383)" in calibration
    assert "CH2 ADS1115 force 0x48 (AIN0 belly FSR, AIN1 jaw FSR; single-ended to GND)" in (
        WIRING.read_text()
    )


def test_haptic_trigger_does_not_claim_a_servo_pin_or_adc_channel():
    source = (FW / "lib/AccessorySensors/AccessorySensors.cpp").read_text()
    docs = WIRING.read_text()
    assert "Action::TurnOn ? 0x04U : 0x00U" in source
    assert "write8(0x20, 0x15, expected)" in source
    assert "CH5 MCP23017 0x20 (GPIOA mandatory dock, GPB0/GPB1 slow reed/PIR," in docs
    assert "GPB2 lab-only haptic edge)" in docs
    assert "CD74HC123/AO3400" in docs
    assert "DRV2605L is not allocated" in docs
