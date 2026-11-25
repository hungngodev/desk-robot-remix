#pragma once
#include <cstddef>
#include "FreeRTOS.h"
using RingbufHandle_t = void*;
void* xRingbufferReceive(RingbufHandle_t ring, std::size_t* size, TickType_t wait);
void vRingbufferReturnItem(RingbufHandle_t ring, void* item);
