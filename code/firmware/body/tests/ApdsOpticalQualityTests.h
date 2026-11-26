#pragma once
#include "ApdsOpticalQuality.h"

// These compile-time regressions are included by accessory_math_tests.cpp.
static_assert(desk_robot::apds_rgbc_quality(1, 0, 65534, 0, 0, 0).valid);
static_assert(desk_robot::apds_rgbc_quality(1, 0, 65535, 0, 0, 0).saturated);
static_assert(!desk_robot::apds_rgbc_quality(1, 0, 65535, 0, 0, 0).valid);
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 65535, 0, 0).saturated);
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 65535, 0).saturated);
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 0, 65535).saturated);
static_assert(desk_robot::apds_rgbc_quality(0x81, 0, 10, 10, 10, 10).saturated);
static_assert(!desk_robot::apds_rgbc_quality(0, 0, 10, 10, 10, 10).valid);
static_assert(desk_robot::apds_rgbc_quality(1, 255, 1024, 0, 0, 0).valid);
static_assert(desk_robot::apds_rgbc_quality(1, 255, 1025, 0, 0, 0).saturated);
static_assert(desk_robot::apds_rgbc_quality(1, 0, 0, 0, 0, 0).valid);
static_assert(!desk_robot::apds_proximity_saturated(254));
static_assert(desk_robot::apds_proximity_saturated(255));
