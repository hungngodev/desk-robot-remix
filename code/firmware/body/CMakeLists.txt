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
target_include_directories(body_control PUBLIC lib/BodyControl lib/PulsePad lib/AccessorySensors lib/TerminalIr)
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
add_executable(optional_i2c_pack_shunt_tests
  tests/optional_i2c_io_tests.cpp
  lib/AccessorySensors/AccessorySensors.cpp
  lib/PulsePad/PulsePad.cpp
  lib/ExpansionTouch/ExpansionTouch.cpp)
target_include_directories(optional_i2c_pack_shunt_tests PRIVATE
  tests/fakes lib/AccessorySensors lib/PulsePad lib/ExpansionTouch)
target_compile_definitions(optional_i2c_pack_shunt_tests PRIVATE
  DESK_ROBOT_STEPPER=1 DESK_ROBOT_PACK_SHUNT_MOHM=5)
target_compile_features(optional_i2c_pack_shunt_tests PRIVATE cxx_std_11)
target_compile_options(optional_i2c_pack_shunt_tests PRIVATE
  -Wall -Wextra -Wpedantic -Werror)

# Exercise the identical bounded FIFO and mux driver with the alternative
# channel interpretation, without choosing it for an unverified physical PCB.
add_executable(optional_i2c_reversed_fifo_tests
  tests/optional_i2c_io_tests.cpp
  lib/AccessorySensors/AccessorySensors.cpp
  lib/PulsePad/PulsePad.cpp
  lib/ExpansionTouch/ExpansionTouch.cpp)
target_include_directories(optional_i2c_reversed_fifo_tests PRIVATE
  tests/fakes lib/AccessorySensors lib/PulsePad lib/ExpansionTouch)
target_compile_definitions(optional_i2c_reversed_fifo_tests PRIVATE
  DESK_ROBOT_STEPPER=1 DESK_ROBOT_MAX30102_FIFO_IR_FIRST=1)
target_compile_features(optional_i2c_reversed_fifo_tests PRIVATE cxx_std_11)
target_compile_options(optional_i2c_reversed_fifo_tests PRIVATE
  -Wall -Wextra -Wpedantic -Werror)

add_executable(mcp_contact_evidence_tests tests/mcp_contact_evidence_tests.cpp)
target_include_directories(mcp_contact_evidence_tests PRIVATE lib/BodyControl)
target_link_libraries(mcp_contact_evidence_tests PRIVATE body_control)
target_compile_features(mcp_contact_evidence_tests PRIVATE cxx_std_11)
target_compile_options(mcp_contact_evidence_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(pack_current_tests tests/pack_current_tests.cpp)
target_include_directories(pack_current_tests PRIVATE lib/AccessorySensors)
target_compile_features(pack_current_tests PRIVATE cxx_std_11)
target_compile_options(pack_current_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(reply_tx_queue_tests tests/reply_tx_queue_tests.cpp)
target_include_directories(reply_tx_queue_tests PRIVATE lib/ReplyTxQueue)
target_compile_features(reply_tx_queue_tests PRIVATE cxx_std_11)
target_compile_options(reply_tx_queue_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(motor_heartbeat_tests tests/motor_heartbeat_tests.cpp)
target_include_directories(motor_heartbeat_tests PRIVATE lib/BodyControl)
target_compile_features(motor_heartbeat_tests PRIVATE cxx_std_11)
target_compile_options(motor_heartbeat_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(motor_heartbeat_ndebug_tests tests/motor_heartbeat_tests.cpp)
target_include_directories(motor_heartbeat_ndebug_tests PRIVATE lib/BodyControl)
target_compile_definitions(motor_heartbeat_ndebug_tests PRIVATE NDEBUG=1)
target_compile_features(motor_heartbeat_ndebug_tests PRIVATE cxx_std_11)
target_compile_options(motor_heartbeat_ndebug_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(mcp_port_direction_tests tests/mcp_port_direction_tests.cpp)
target_include_directories(mcp_port_direction_tests PRIVATE lib/AccessorySensors)
target_compile_features(mcp_port_direction_tests PRIVATE cxx_std_11)
target_compile_options(mcp_port_direction_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(haptic_pulse_tests tests/haptic_pulse_tests.cpp)
target_include_directories(haptic_pulse_tests PRIVATE lib/AccessorySensors)
target_compile_features(haptic_pulse_tests PRIVATE cxx_std_11)
target_compile_options(haptic_pulse_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(haptic_mcp_bus_tests tests/haptic_mcp_bus_tests.cpp
  lib/AccessorySensors/AccessorySensors.cpp)
target_include_directories(haptic_mcp_bus_tests PRIVATE
  tests/fakes lib/AccessorySensors)
target_compile_definitions(haptic_mcp_bus_tests PRIVATE
  DESK_ROBOT_STEPPER=1 DESK_ROBOT_ENABLE_HAPTIC=1)
target_compile_features(haptic_mcp_bus_tests PRIVATE cxx_std_11)
target_compile_options(haptic_mcp_bus_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(terminal_ir_tests tests/terminal_ir_tests.cpp)
target_include_directories(terminal_ir_tests PRIVATE lib/TerminalIr)
target_compile_features(terminal_ir_tests PRIVATE cxx_std_11)
target_compile_options(terminal_ir_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

# Exercise the actual legacy RMT poll owner, not just its portable queue gate.
add_executable(terminal_ir_poll_tests
  tests/terminal_ir_poll_tests.cpp lib/TerminalIr/TerminalIr.cpp)
target_include_directories(terminal_ir_poll_tests PRIVATE
  tests/fakes/terminal_ir lib/TerminalIr)
target_compile_definitions(terminal_ir_poll_tests PRIVATE DESK_ROBOT_STEPPER=1)
target_compile_features(terminal_ir_poll_tests PRIVATE cxx_std_11)
target_compile_options(terminal_ir_poll_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(pn532_frames_tests tests/pn532_frames_tests.cpp)
target_include_directories(pn532_frames_tests PRIVATE lib/AccessorySensors)
target_compile_features(pn532_frames_tests PRIVATE cxx_std_11)
target_compile_options(pn532_frames_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

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
add_executable(tof_mux_tests tests/tof_mux_tests.cpp lib/TofBus/TofBus.cpp)
target_include_directories(tof_mux_tests PRIVATE tests/fakes lib/TofBus
  lib/CliffGuard lib/BerryImu lib/AccessorySensors)
target_compile_definitions(tof_mux_tests PRIVATE DESK_ROBOT_STEPPER=1
  DESK_ROBOT_EXTRA_RANGERS=1)
target_link_libraries(tof_mux_tests PRIVATE body_control)
target_compile_features(tof_mux_tests PRIVATE cxx_std_11)
target_compile_options(tof_mux_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
# Exercise the real Arduino-guarded LSM9DS0 register writes with a host Wire fake.
# This is not physical calibration or a validation of the selected MPU6050.
add_executable(berry_imu_register_tests
  tests/berry_imu_register_tests.cpp
  lib/BerryImu/BerryImu.cpp)
target_include_directories(berry_imu_register_tests PRIVATE
  tests/imu_fakes lib/BerryImu)
target_compile_definitions(berry_imu_register_tests PRIVATE ARDUINO=1)
target_compile_features(berry_imu_register_tests PRIVATE cxx_std_11)
target_compile_options(berry_imu_register_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(berry_imu_tests tests/berry_imu_tests.cpp)
target_link_libraries(berry_imu_tests PRIVATE body_control berry_imu)
target_compile_options(berry_imu_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
# Pure sensor acquisition and wrap inference. Never qualifies wheel displacement.
add_executable(wheel_pose_integrator_tests tests/wheel_pose_integrator_tests.cpp)
target_include_directories(wheel_pose_integrator_tests PRIVATE lib/BodyControl lib/AccessorySensors)
target_compile_features(wheel_pose_integrator_tests PRIVATE cxx_std_11)
target_compile_options(wheel_pose_integrator_tests PRIVATE
  -Wall -Wextra -Wpedantic -Werror)

add_executable(imu_yaw_capture_tests tests/imu_yaw_capture_tests.cpp)
target_include_directories(imu_yaw_capture_tests PRIVATE lib/BodyControl lib/BerryImu)
target_compile_features(imu_yaw_capture_tests PRIVATE cxx_std_11)
target_compile_options(imu_yaw_capture_tests PRIVATE
  -Wall -Wextra -Wpedantic -Werror)

add_executable(wheel_angle_capture_tests tests/wheel_angle_capture_tests.cpp)
target_include_directories(wheel_angle_capture_tests PRIVATE
  lib/BodyControl lib/AccessorySensors)
target_compile_features(wheel_angle_capture_tests PRIVATE cxx_std_11)
target_compile_options(wheel_angle_capture_tests PRIVATE
  -Wall -Wextra -Wpedantic -Werror)

add_executable(pose_read_only_tests tests/pose_read_only_tests.cpp)
target_link_libraries(pose_read_only_tests PRIVATE body_control)
target_compile_features(pose_read_only_tests PRIVATE cxx_std_11)
target_compile_options(pose_read_only_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(body_tests tests/body_tests.cpp)
target_link_libraries(body_tests PRIVATE body_control)
target_compile_options(body_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(stepper_tests tests/stepper_tests.cpp)
target_link_libraries(stepper_tests PRIVATE stepper_drive)
target_compile_options(stepper_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(cliff_tests tests/cliff_tests.cpp)
target_link_libraries(cliff_tests PRIVATE cliff_guard)
target_compile_options(cliff_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(servo_center_bench_tests tests/servo_center_bench_tests.cpp)
target_include_directories(servo_center_bench_tests PRIVATE
    tests/fakes/servo_bench include lib/ServoCenterBench lib/ReplyTxQueue)
target_compile_features(servo_center_bench_tests PRIVATE cxx_std_11)
target_compile_options(servo_center_bench_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(vl53l0x_bench_tests tests/vl53l0x_bench_tests.cpp)
target_include_directories(vl53l0x_bench_tests PRIVATE tests/fakes/vl53_bench include)
target_compile_definitions(vl53l0x_bench_tests PRIVATE DESK_ROBOT_STEPPER=1)
target_compile_features(vl53l0x_bench_tests PRIVATE cxx_std_17)
target_compile_options(vl53l0x_bench_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_executable(guarded_body_tests tests/guarded_body_tests.cpp)
target_include_directories(guarded_body_tests PRIVATE lib/ReplyTxQueue)
target_link_libraries(guarded_body_tests PRIVATE body_control stepper_drive)
target_compile_options(guarded_body_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
get_property(body_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
if(BODY_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  foreach(target IN LISTS body_targets)
    # UBSan normally recovers and can leave CTest green after undefined behavior.
    target_compile_options(${target} PRIVATE -fsanitize=address,undefined
      -fno-sanitize-recover=undefined -fno-omit-frame-pointer)
    target_link_options(${target} PRIVATE -fsanitize=address,undefined)
  endforeach()
endif()

enable_testing()
function(body_add_test name target)
  add_test(NAME "${name}" COMMAND "${target}" ${ARGN})
  set_property(DIRECTORY APPEND PROPERTY BODY_CTEST_TARGETS "${target}")
endfunction()
body_add_test(servo_center_one_shot_usb_gate servo_center_bench_tests)
body_add_test(vl53l0x_bench_fail_closed_io vl53l0x_bench_tests)
body_add_test(mcp_gpio_b_independent_contact_acquisitions mcp_contact_evidence_tests)
body_add_test(optional_sensor_bus_protocol optional_i2c_io_tests)
body_add_test(optical_fifo_swapped_carrier_behavior optional_i2c_reversed_fifo_tests)
body_add_test(bounded_uart_response_queue reply_tx_queue_tests)
body_add_test(dc_cpu_watchdog_heartbeat_gating motor_heartbeat_tests)
body_add_test(dc_cpu_watchdog_heartbeat_ndebug motor_heartbeat_ndebug_tests)
body_add_test(signed_battery_shunt_physical_semantics pack_current_tests)
body_add_test(ina226_fresh_pack_current_i2c_bus optional_i2c_pack_shunt_tests)
body_add_test(haptic_edge_rate_and_fault_gating haptic_pulse_tests)
body_add_test(haptic_mcp23017_dock_bus_gating haptic_mcp_bus_tests)
body_add_test(mcp23017_direction_lock_and_reset mcp_port_direction_tests)
body_add_test(pn532_bounded_read_only_protocol pn532_frames_tests)
body_add_test(independent_nec_terminal_beacon_evidence terminal_ir_tests)
body_add_test(legacy_rmt_terminal_ir_poll_quarantine terminal_ir_poll_tests)
body_add_test(optional_sensor_register_math accessory_math_tests)
body_add_test(paw_pulse_fifo_parser pulse_raw_tests)
body_add_test(safety_priority_ranging_schedule range_scan_tests)
body_add_test(verified_tca_selected_channel_cliff_safety tof_mux_tests)
body_add_test(berry_imu_identity_and_telemetry berry_imu_tests)
body_add_test(lsm9ds0_six_axis_block_data_update berry_imu_register_tests)
body_add_test(stepper_phase_and_timing stepper_tests)
body_add_test(cliff_fault_policy cliff_tests)
body_add_test(wheel_pose_math_requires_measured_origin wheel_pose_integrator_tests)
body_add_test(imu_yaw_capture_freshness_and_bias imu_yaw_capture_tests)
body_add_test(wheel_angle_capture_freshness_and_wrap wheel_angle_capture_tests)
body_add_test(body_read_only_pose_unavailable_contract pose_read_only_tests)
body_add_test(guarded_body_integration guarded_body_tests)
foreach(scenario
    attitude_norm_root_boundaries
    disarmed_boot arm_clears_old_motion drive_limits drive_duration
    overlapping_drive_replaces_pending_pulse
    keepalive_does_not_extend_drive invalid_does_not_renew
    queries_do_not_renew smooth_servos keepalive_extends_servo_lease
    stop_freezes_servos explicit_disarm_detaches watchdog_holds_servos
    rollover_timers strict_integer_parser malformed_atomicity
    overlong_frame_recovery framing serial_idle_frame_timeout serial_total_frame_timeout
    independent_receivers status_honesty
    rejected_grip_does_not_renew_watchdog
    guarded_head_timeout_cannot_rearm_from_reconnected_uart
    guarded_transition_sequences
    guarded_reboot_fault_matrix
    deterministic_stream_stress)
  body_add_test(${scenario} body_tests ${scenario})
endforeach()

include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/VerifyHostTests.cmake")
