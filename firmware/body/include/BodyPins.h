#pragma once

#ifndef DESK_ROBOT_STEPPER
#define DESK_ROBOT_STEPPER 0
#endif

namespace body_pins {
// ESP32-WROOM-32 dev board: no flash, UART0, input-only or strapping pins used.
constexpr int kUartRx = 16;
constexpr int kUartTx = 17;
#if DESK_ROBOT_STEPPER
constexpr int kLeftStepperPins[] = {13, 14, 25, 26};
constexpr int kRightStepperPins[] = {27, 32, 33, 23};
constexpr int kMotorPins[] = {13, 14, 25, 26, 27, 32, 33, 23};
constexpr int kSensorSda = 21;
constexpr int kSensorScl = 22;
constexpr int kMuxReset = 4;
#else
// DRV8833: xIN1 positive PWM / xIN2 low, reversed for negative; both low = coast.
constexpr int kLeftIn1 = 25;
constexpr int kLeftIn2 = 26;
constexpr int kRightIn1 = 27;
constexpr int kRightIn2 = 32;
constexpr int kMotorPins[] = {kLeftIn1, kLeftIn2, kRightIn1, kRightIn2};
constexpr int kMotorChannels[] = {0, 1, 2, 3};
constexpr int kMotorFrequency = 20000;
constexpr int kMotorResolution = 8;
#endif
constexpr int kLiftServo = 18;
constexpr int kGripServo = 19;
constexpr int kServoPins[] = {kLiftServo, kGripServo};
constexpr int kServoChannels[] = {4, 5};
constexpr int kServoFrequency = 50;
constexpr int kServoResolution = 16;
// Conservative generic 1..2 ms span; calibrate actual mechanism before loading.
constexpr int kServoMinUs = 1000;
constexpr int kServoMaxUs = 2000;
}  // namespace body_pins
