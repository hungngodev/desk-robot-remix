#pragma once

#ifndef DESK_ROBOT_STEPPER
#define DESK_ROBOT_STEPPER 0
#endif

namespace body_pins {
// ESP32-WROOM-32: no flash, UART0 or strapping pins allocated; input-only
// pins are reserved for inputs with appropriate external bias.
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
constexpr int kMotorPins[] = {kLeftStepperPins[0], kLeftStepperPins[1],
                              kLeftStepperPins[2], kLeftStepperPins[3],
                              kRightStepperPins[0], kRightStepperPins[1],
                              kRightStepperPins[2], kRightStepperPins[3]};
#endif
#if DESK_ROBOT_STEPPER || (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
constexpr int kSensorSda = 21;
constexpr int kSensorScl = 22;
// GPIO4 is reserved by the project pin policy (not an ESP32 strap pin).
// Do not connect the multiplexer RESET there. Pull the active-low
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
// Accessory mux 0x71 uses bounded I2C polling, not dedicated MCU IRQs.
// -1 means no WROOM allocation; module-specific reset/bias still needs review.
constexpr int kCap1188AlertPin = -1;
constexpr int kMax30102IntPin = -1;
constexpr int kApds9960IntPin = -1;
constexpr int kPn532IrqPin = -1;
constexpr int kPn532ResetPin = -1;
constexpr int kMcp23017IntAPin = -1;
constexpr int kMcp23017IntBPin = -1;
static_assert(kCap1188AlertPin == -1 && kMax30102IntPin == -1 &&
              kApds9960IntPin == -1 && kPn532IrqPin == -1 &&
              kPn532ResetPin == -1 && kMcp23017IntAPin == -1 &&
              kMcp23017IntBPin == -1,
              "Accessory control pins are unallocated in the polled profiles");
// Dock seat/charger status is NOT a WROOM output or a power-enable pin.
// MCP23017 at accessory mux 0x71 lane 5, address 0x20, BANK=0:
// GPA0/1 are independent NC seat switches; GPA2/3 are active-low
// BQ24075 PGOOD/CHG open-drain status outputs, pulled up only to 3.3V.
// Keep all GPIOA bits INPUT (IODIRA=0xFF); never write GPIOA/OLATA.
// Raw 5V dock contacts must never connect to these logic inputs.
// McpPortDirectionLock owns runtime checks; wiring/short protection
// and correct BANK configuration still require physical qualification.
// Slow magnetic hat/reed and PIR inputs move to MCP23017 GPIOB0 and GPIOB1.
// They are not WROOM GPIOs and cannot capture 560us IR pulses.
#endif

// DRV8833: xIN1 positive PWM / xIN2 low, reversed for negative; both low = coast.
// Keep the alternative harness names available to the motor-disconnected bench.
constexpr int kLeftIn1 = 25;
constexpr int kLeftIn2 = 26;
constexpr int kRightIn1 = 27;
constexpr int kRightIn2 = 32;
#if !DESK_ROBOT_STEPPER
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
// Only the deliberately approved WROOM output-capable allocation is allowed.
// GPIO4 remains reserved by policy, not because it is a silicon strap pin.
constexpr bool approved_output_pin(int pin) {
  return pin == 13 || pin == 14 || pin == 16 || pin == 17 || pin == 18 ||
         pin == 19 || pin == 21 || pin == 22 || pin == 23 || pin == 25 ||
         pin == 26 || pin == 27 || pin == 32 || pin == 33;
}
template <unsigned N>
constexpr bool all_output_capable(const int (&pins)[N], unsigned i = 0) {
  return i == N || (approved_output_pin(pins[i]) && all_output_capable(pins, i + 1));
}
template <unsigned N>
constexpr bool all_distinct(const int (&pins)[N], unsigned i = 0, unsigned j = 1) {
  return i >= N ? true : j >= N ? all_distinct(pins, i + 1, i + 2) :
      pins[i] != pins[j] && all_distinct(pins, i, j + 1);
}
// Keep the arrays actually traversed by setup/stop in lockstep with the
// allocation below. Checking only the first N entries silently misses an
// appended pin/channel; checking only named pins misses a replaced alias.
template <unsigned N>
constexpr unsigned count(const int (&)[N]) { return N; }
static_assert(count(kServoPins) == 2 && kServoPins[0] == kLiftServo &&
              kServoPins[1] == kGripServo && count(kServoChannels) == 2,
              "Servo GPIO/channel arrays must match the two servo owners");
#if DESK_ROBOT_STEPPER
static_assert(count(kLeftStepperPins) == 4 && count(kRightStepperPins) == 4 &&
              count(kMotorPins) == 8 &&
              kMotorPins[0] == kLeftStepperPins[0] && kMotorPins[1] == kLeftStepperPins[1] &&
              kMotorPins[2] == kLeftStepperPins[2] && kMotorPins[3] == kLeftStepperPins[3] &&
              kMotorPins[4] == kRightStepperPins[0] && kMotorPins[5] == kRightStepperPins[1] &&
              kMotorPins[6] == kRightStepperPins[2] && kMotorPins[7] == kRightStepperPins[3],
              "Stepper GPIO arrays must match the eight phase owners");
#else
static_assert(count(kMotorPins) == 4 && count(kMotorChannels) == 4 &&
              kMotorPins[0] == kLeftIn1 && kMotorPins[1] == kLeftIn2 &&
              kMotorPins[2] == kRightIn1 && kMotorPins[3] == kRightIn2,
              "DC GPIO/channel arrays must match the four PWM owners");
#endif
constexpr int kAllocatedOutputPins[] = {
    kUartRx, kUartTx, kLiftServo, kGripServo,
    kMotorPins[0], kMotorPins[1], kMotorPins[2], kMotorPins[3],
#if DESK_ROBOT_STEPPER
    kMotorPins[4], kMotorPins[5], kMotorPins[6], kMotorPins[7],
#elif defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
    kDcHeartbeatPin,
#endif
#if DESK_ROBOT_STEPPER || (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
    kSensorSda, kSensorScl,
#endif
};
static_assert(all_output_capable(kAllocatedOutputPins), "WROOM output pin not approved");
static_assert(all_distinct(kAllocatedOutputPins), "WROOM GPIO allocation overlaps");
#if DESK_ROBOT_STEPPER || (defined(DESK_ROBOT_FULL_SENSORS) && DESK_ROBOT_FULL_SENSORS)
static_assert(kTouchOutput == 34 && kBumperInput == 35 &&
              kTerminalIrLeftInput == 36 && kTerminalIrRightInput == 39,
              "WROOM input-only harness allocation changed");
#endif
// Conservative generic 1..2 ms span; calibrate actual mechanism before loading.
constexpr int kServoMinUs = 1000;
constexpr int kServoMaxUs = 2000;
}  // namespace body_pins
