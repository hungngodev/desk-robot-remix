#pragma once

#ifndef DESK_ROBOT_STEPPER
#define DESK_ROBOT_STEPPER 0
#endif

namespace body_pins {
// ESP32-WROOM-32 dev board: no flash, UART0, input-only or strapping pins used.
constexpr int kUartRx = 16;
constexpr int kUartTx = 17;
#if DESK_ROBOT_STEPPER
// The historical ULN2003 stepper profile has NO independent CPU-halt
// actuator power cutoff equivalent to the DC watchdog/CD74HC123 nSLEEP
// path. Software watchdog and CliffGuard alone cannot qualify a printed
// mobile unit. Require a physically qualified independent motor-rail
// cutoff before production stepper driving or product purchase release.
constexpr int kLeftStepperPins[] = {13, 14, 25, 26};
constexpr int kRightStepperPins[] = {27, 32, 33, 23};
constexpr int kMotorPins[] = {13, 14, 25, 26, 27, 32, 33, 23};
#endif
#if DESK_ROBOT_STEPPER || (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
constexpr int kSensorSda = 21;
constexpr int kSensorScl = 22;
// No spare boot-safe output on this pin map. GPIO4 is a boot strapping
// pin; do not connect the multiplexer RESET there. Pull the active-low
// TCA9548A RESET to 3.3V (through the module's required pull-up).
constexpr int kMuxReset = -1;
static_assert(kMuxReset == -1,
              "TCA9548A RESET must be passively tied high, never WROOM GPIO4");
// Adafruit AT42QT1010 OUT: active high, 3.3V logic. GPIO34 is input only.
constexpr int kTouchOutput = 34;
// Reserved disabled-by-default input-only GPIOs. No internal pull resistors.
// NC switches wired in series to ground, external 3.3V pullup.
// Normal continuity drives LOW; collision or broken wire opens -> HIGH trip.
constexpr int kBumperInput = 35;
// Proposed two demodulated 38kHz terminal dock IR receiver inputs.
// Input-only, external pullups/active receiver output; no internal bias.
// A bounded NEC receiver decoder is implemented behind the lab/full flag.
// Its evidence is read-only: no qualified dock homing, bearing estimate,
// contact charging authorizer or calibrated IR path exists.
// ESP32 GPIO36/39 RTC/ADC glitch erratum needs RMT filtering and bench tests.
constexpr int kTerminalIrLeftInput = 36;
constexpr int kTerminalIrRightInput = 39;
// Slow magnetic hat/reed and PIR inputs move to MCP23017 GPIOB0 and GPIOB1.
// They are not WROOM GPIOs and cannot capture 560us IR pulses.
#endif

#if !DESK_ROBOT_STEPPER
// DRV8833: xIN1 positive PWM / xIN2 low, reversed for negative; both low = coast.
constexpr int kLeftIn1 = 25;
constexpr int kLeftIn2 = 26;
constexpr int kRightIn1 = 27;
constexpr int kRightIn2 = 32;
constexpr int kMotorPins[] = {kLeftIn1, kLeftIn2, kRightIn1, kRightIn2};
constexpr int kMotorChannels[] = {0, 1, 2, 3};
constexpr int kMotorFrequency = 20000;
constexpr int kMotorResolution = 8;
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
// GPIO23 is intentionally used by the STEP drive. Only the DC alternative
// frees it. Tie GPIO23 to the second half of the existing CD74HC123 timer;
// NEVER directly tie GPIO23 to the motor driver's nSLEEP input.
// Guarded DRV8833 full DC build: MCP23017 at 0x71 lane 5 GPB3 reads
// nFAULT (open drain, active LOW). Wire a ~4.7k 3.3V pullup at the
// DRV8833 end and a 100k pulldown at the GPB3 end, with B3 internal
// pullup OFF. Disconnected nFAULT harness must measure LOW/fault; verify
// actual carrier exposes nFAULT and its logic before connecting motors.
// Do not connect a 5V pullup to MCP23017 3.3V GPIO.
constexpr int kDcHeartbeatPin = 23;
static_assert(kDcHeartbeatPin != kLeftIn1 && kDcHeartbeatPin != kLeftIn2 &&
              kDcHeartbeatPin != kRightIn1 && kDcHeartbeatPin != kRightIn2,
              "CPU heartbeat cannot share a DC PWM input");
#endif
#endif
constexpr int kLiftServo = 18;
constexpr int kGripServo = 19;
constexpr int kServoPins[] = {kLiftServo, kGripServo};
constexpr int kServoChannels[] = {4, 5};
constexpr int kServoFrequency = 50;
constexpr int kServoResolution = 16;
// Arduino-ESP32 LEDC on the pinned ESP32-WROOM profile assigns one hardware
// timer to each consecutive pair of channels: 0/1 -> timer 0, 2/3 -> timer 1,
// 4/5 -> timer 2. The firmware uses direct ledcSetup(), not ESP32Servo.
// Reject a future pin/channel or PWM frequency refactor that would put a
// 50 Hz servo on a 20 kHz DRV8833 motor timer. This is a source/build
// contract, NOT evidence the actual motor and servo PCB is electrically safe.
static_assert(kServoChannels[0] == 4 && kServoChannels[1] == 5 &&
              kServoFrequency == 50 && kServoResolution == 16,
              "Servo outputs must own 50 Hz LEDC timer 2");
#if !DESK_ROBOT_STEPPER
static_assert(kMotorChannels[0] == 0 && kMotorChannels[1] == 1 &&
              kMotorChannels[2] == 2 && kMotorChannels[3] == 3 &&
              kMotorFrequency == 20000 && kMotorResolution == 8,
              "DC motor outputs must use isolated LEDC timers 0/1");
static_assert(kLeftIn1 != kLeftIn2 && kLeftIn1 != kRightIn1 &&
              kLeftIn1 != kRightIn2 && kLeftIn2 != kRightIn1 &&
              kLeftIn2 != kRightIn2 && kRightIn1 != kRightIn2 &&
              kLiftServo != kLeftIn1 && kLiftServo != kLeftIn2 &&
              kLiftServo != kRightIn1 && kLiftServo != kRightIn2 &&
              kGripServo != kLeftIn1 && kGripServo != kLeftIn2 &&
              kGripServo != kRightIn1 && kGripServo != kRightIn2,
              "Motor and servo GPIO assignments must never overlap");
#endif
// Conservative generic 1..2 ms span; calibrate actual mechanism before loading.
constexpr int kServoMinUs = 1000;
constexpr int kServoMaxUs = 2000;
}  // namespace body_pins
