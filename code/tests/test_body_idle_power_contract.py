"""Guard idle power semantics at the actual body firmware integration boundary.

These are source contracts, not proof of nSLEEP voltage, rail current or
mechanical payload retention. No sensor supply switch is assumed.
"""
import re
from pathlib import Path

import pytest

BODY = Path(__file__).resolve().parents[1] / "firmware/body"


def _section(path, start, end):
    source = (BODY / path).read_text()
    return source.split(start, 1)[1].split(end, 1)[0]


def test_idle_wheels_cannot_extend_independent_motor_heartbeat():
    heartbeat = _section("src/main.cpp", "void enforce_motor_heartbeat(",
                         "void apply_outputs()")
    assert "DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED &&" in heartbeat
    assert "pwm_ready && drive.armed &&" in heartbeat
    assert "(drive.left != 0 || drive.right != 0)" in heartbeat
    assert "motor_heartbeat.update(millis(), allow_heartbeat)" in heartbeat
    assert "!motor_heartbeat.check_authority(millis(), allow_heartbeat)" in heartbeat
    assert "digitalWrite(body_pins::kDcHeartbeatPin, LOW)" in heartbeat
    assert "control.motor_watchdog_trip()" in heartbeat


def test_explicit_disarm_does_not_clear_fault_or_restart_servo_targets():
    path = "lib/BodyControl/BodyControl.cpp"
    disarm = _section(path, "void BodyControl::force_disarm()", "\n}")
    assert "stop_motion();" in disarm
    assert "state_.armed = false;" in disarm
    assert "state_.servos_attached = false;" in disarm
    assert "latched_" not in disarm
    stop = _section(path, "void BodyControl::stop_motion()", "\n}")
    for statement in (
        "state_.left = 0;", "state_.right = 0;", "drive_duration_ms_ = 0;",
        "state_.lift_target = state_.lift;", "state_.grip_target = state_.grip;",
        "jaw_sample_motion_budget_ = 0;",
    ):
        assert statement in stop
    fault = _section(path, "void BodyControl::motor_watchdog_trip()", "\n}")
    assert "motor_watchdog_latched_ = true;" in fault
    assert "state_.armed = false;" in fault
    assert "servos_attached = false" not in fault


def test_idle_keeps_safety_sensor_acquisition_and_servo_detach_separate():
    main = (BODY / "src/main.cpp").read_text()
    loop = main.split("void loop() {", 1)[1]
    for poll in (
        "tof.poll(cliff_guard, scan_ms);",
        "if (tof.clients_accessible()) berry_imu.poll(millis());",
        "if (tof.clients_accessible() && !accessories.poll(millis()))",
        "tof.note_shared_mux_fault(cliff_guard);",
        "control.set_accessories(accessories.readings(), millis());",
    ):
        assert poll in loop
    # Do not conflate cutting a PWM signal with disconnecting the 5 V rail.
    detach = main.split("!state.servos_attached && servo_attached", 1)[1]
    detach = detach.split("if (servo_attached &&", 1)[0]
    assert "digitalWrite(pin, LOW)" in detach
    assert "ledcDetachPin(pin);" in detach
    assert "pinMode(pin, OUTPUT);" in detach


def test_idle_wake_requires_local_rearm_to_clear_missed_heartbeat():
    main = (BODY / "src/main.cpp").read_text()
    command = main.split("void process_input(", 1)[1].split("void loop() {", 1)[0]
    reset = ('if (completed && local_usb && strcmp(reply, "OK rearm") == 0)\n'
             '      motor_heartbeat.reset();')
    assert reset in command
    # The other reset is in setup(), after the output has been driven LOW.
    assert main.count("motor_heartbeat.reset();") == 2
    assert "motor_heartbeat.reset();" not in main.split("void loop() {", 1)[1]


_I2C_POLL = re.compile(r"\b(tof|berry_imu|accessories|cap1188|paw_pulse)\s*\.\s*poll\s*\(")


def _assert_i2c_loop_ownership(source: str) -> None:
    # Source contract: comments must not satisfy or violate ownership.
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    before, loop = source.split("void loop() {", 1)
    assert not _I2C_POLL.search(before), "I2C poll outside control loop"
    assert sorted(_I2C_POLL.findall(loop)) == [
        "accessories", "berry_imu", "cap1188", "paw_pulse", "tof",
    ]
    handler = before.split("void process_input(", 1)[1].split("void setup()", 1)[0]
    assert not re.search(r"\bWire\s*\.", handler), "direct I2C in UART handler"


def test_uart_diagnostics_leave_i2c_polling_to_control_loop():
    _assert_i2c_loop_ownership((BODY / "src/main.cpp").read_text())


@pytest.mark.parametrize("injected", [
    "tof.poll(cliff_guard, millis());",
    "accessories.poll(millis());",
    "cap1188 . poll(millis(), zones);",
    "Wire.beginTransmission(0x71);",
])
def test_i2c_ownership_guard_detects_uart_poll_mutations(injected: str):
    main = (BODY / "src/main.cpp").read_text()
    assert "receiver.feed(" in main
    mutant = main.replace("receiver.feed(", injected + "\n    receiver.feed(", 1)
    with pytest.raises(AssertionError, match="I2C"):
        _assert_i2c_loop_ownership(mutant)
