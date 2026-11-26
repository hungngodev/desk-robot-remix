#pragma once
#include "ApdsOpticalQuality.h"

// Deliberately default-initialize, not value-initialize with braces.
constexpr desk_robot::ApdsRgbcQuality cold_rgbc;
static_assert(!cold_rgbc.valid && !cold_rgbc.saturated, "RGB evidence must start invalid");

// These compile-time regressions are included by accessory_math_tests.cpp.
static_assert(desk_robot::apds_rgbc_quality(1, 0, 65534, 0, 0, 0).valid, "Below rail is valid");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 65535, 0, 0, 0).saturated, "Clear rail saturates");
static_assert(!desk_robot::apds_rgbc_quality(1, 0, 65535, 0, 0, 0).valid, "Saturation invalidates RGB");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 65535, 0, 0).saturated, "Red rail saturates");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 65535, 0).saturated, "Green rail saturates");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 0, 65535).saturated, "Blue rail saturates");
static_assert(desk_robot::apds_rgbc_quality(0x81, 0, 10, 10, 10, 10).saturated, "CPSAT wins");
static_assert(!desk_robot::apds_rgbc_quality(0, 0, 10, 10, 10, 10).valid, "Missing AVALID invalidates RGB");
static_assert(desk_robot::apds_rgbc_quality(1, 255, 1024, 0, 0, 0).valid, "Below short exposure ceiling is valid");
static_assert(desk_robot::apds_rgbc_quality(1, 255, 1025, 0, 0, 0).saturated, "Short exposure ceiling saturates");
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 0, 0).valid, "Zero counts are valid with AVALID");
static_assert(!desk_robot::apds_proximity_saturated(254), "Below proximity rail is valid");
static_assert(desk_robot::apds_proximity_saturated(255), "Proximity rail saturates");
static_assert(desk_robot::apds_rgbc_ceiling(192) == 65535U, "64 cycles clamp to rail");
static_assert(desk_robot::apds_rgbc_ceiling(193) == 64513U, "63 cycles limit counts");
static_assert(desk_robot::apds_rgbc_quality(0x80, 255, 0, 0, 0, 0).saturated,
              "CPSAT is independent of AVALID");
