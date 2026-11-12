#pragma once
#include <cstddef>
#include <cstdint>

// Minimal host stand-ins for the optional mux RESET path in the ToF adapter.
// Production ESP32 builds always use the real Arduino framework definitions.
#define OUTPUT 1
#define LOW 0
#define HIGH 1
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline void delayMicroseconds(unsigned) {}
inline void delay(unsigned) {}
