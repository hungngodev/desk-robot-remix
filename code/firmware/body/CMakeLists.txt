cmake_minimum_required(VERSION 3.16)
project(desk_robot_body LANGUAGES CXX)

option(BODY_SANITIZERS "Enable host address and undefined behavior sanitizers" OFF)
add_library(cliff_guard lib/CliffGuard/CliffGuard.cpp)
target_include_directories(cliff_guard PUBLIC lib/CliffGuard)
target_compile_features(cliff_guard PUBLIC cxx_std_11)
target_compile_options(cliff_guard PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_library(stepper_drive lib/StepperDrive/StepperDrive.cpp)
target_include_directories(stepper_drive PUBLIC lib/StepperDrive)
target_compile_features(stepper_drive PUBLIC cxx_std_11)
target_compile_options(stepper_drive PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_library(berry_imu lib/BerryImu/BerryImu.cpp)
target_include_directories(berry_imu PUBLIC lib/BerryImu)
target_compile_features(berry_imu PUBLIC cxx_std_11)
target_compile_options(berry_imu PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_library(body_control lib/BodyControl/BodyControl.cpp)
target_include_directories(body_control PUBLIC lib/BodyControl lib/PulsePad lib/AccessorySensors)
target_link_libraries(body_control PUBLIC cliff_guard berry_imu)
target_compile_features(body_control PUBLIC cxx_std_11)
target_compile_options(body_control PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(optional_i2c_io_tests
  tests/optional_i2c_io_tests.cpp
  lib/AccessorySensors/AccessorySensors.cpp
  lib/PulsePad/PulsePad.cpp
  lib/ExpansionTouch/ExpansionTouch.cpp)
target_include_directories(optional_i2c_io_tests PRIVATE
  tests/fakes lib/AccessorySensors lib/PulsePad lib/ExpansionTouch)
target_compile_definitions(optional_i2c_io_tests PRIVATE DESK_ROBOT_STEPPER=1)
target_compile_features(optional_i2c_io_tests PRIVATE cxx_std_11)
target_compile_options(optional_i2c_io_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(accessory_math_tests tests/accessory_math_tests.cpp)
target_include_directories(accessory_math_tests PRIVATE lib/AccessorySensors)
target_compile_features(accessory_math_tests PRIVATE cxx_std_11)
target_compile_options(accessory_math_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(pulse_raw_tests tests/pulse_raw_tests.cpp)
target_include_directories(pulse_raw_tests PRIVATE lib/PulsePad)
target_compile_features(pulse_raw_tests PRIVATE cxx_std_11)
target_compile_options(pulse_raw_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(range_scan_tests tests/range_scan_tests.cpp)
target_include_directories(range_scan_tests PRIVATE lib/TofBus)
target_compile_features(range_scan_tests PRIVATE cxx_std_11)
target_compile_options(range_scan_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(berry_imu_tests tests/berry_imu_tests.cpp)
target_link_libraries(berry_imu_tests PRIVATE body_control berry_imu)
target_compile_options(berry_imu_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(body_tests tests/body_tests.cpp)
target_link_libraries(body_tests PRIVATE body_control)
target_compile_options(body_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(stepper_tests tests/stepper_tests.cpp)
target_link_libraries(stepper_tests PRIVATE stepper_drive)
target_compile_options(stepper_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(cliff_tests tests/cliff_tests.cpp)
target_link_libraries(cliff_tests PRIVATE cliff_guard)
target_compile_options(cliff_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(guarded_body_tests tests/guarded_body_tests.cpp)
target_link_libraries(guarded_body_tests PRIVATE body_control stepper_drive)
target_compile_options(guarded_body_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
if(BODY_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  foreach(target optional_i2c_io_tests accessory_math_tests pulse_raw_tests range_scan_tests berry_imu berry_imu_tests body_control body_tests stepper_drive stepper_tests cliff_guard cliff_tests guarded_body_tests)
    target_compile_options(${target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(${target} PRIVATE -fsanitize=address,undefined)
  endforeach()
endif()

enable_testing()
add_test(NAME optional_sensor_bus_protocol COMMAND optional_i2c_io_tests)
add_test(NAME optional_sensor_register_math COMMAND accessory_math_tests)
add_test(NAME paw_pulse_fifo_parser COMMAND pulse_raw_tests)
add_test(NAME safety_priority_ranging_schedule COMMAND range_scan_tests)
add_test(NAME berry_imu_identity_and_telemetry COMMAND berry_imu_tests)
add_test(NAME stepper_phase_and_timing COMMAND stepper_tests)
add_test(NAME cliff_fault_policy COMMAND cliff_tests)
add_test(NAME guarded_body_integration COMMAND guarded_body_tests)
foreach(scenario
    disarmed_boot arm_clears_old_motion drive_limits drive_duration
    keepalive_does_not_extend_drive invalid_does_not_renew
    queries_do_not_renew smooth_servos keepalive_extends_servo_lease
    stop_freezes_servos explicit_disarm_detaches watchdog_holds_servos
    rollover_timers strict_integer_parser malformed_atomicity
    overlong_frame_recovery framing independent_receivers status_honesty
    deterministic_stream_stress)
  add_test(NAME ${scenario} COMMAND body_tests ${scenario})
endforeach()
