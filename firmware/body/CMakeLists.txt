cmake_minimum_required(VERSION 3.16)
project(desk_robot_body LANGUAGES CXX)

option(BODY_SANITIZERS "Enable host address and undefined behavior sanitizers" OFF)
add_library(body_control lib/BodyControl/BodyControl.cpp)
target_include_directories(body_control PUBLIC lib/BodyControl)
target_compile_features(body_control PUBLIC cxx_std_11)
target_compile_options(body_control PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(body_tests tests/body_tests.cpp)
target_link_libraries(body_tests PRIVATE body_control)
target_compile_options(body_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
if(BODY_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  foreach(target body_control body_tests)
    target_compile_options(${target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(${target} PRIVATE -fsanitize=address,undefined)
  endforeach()
endif()

enable_testing()
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
