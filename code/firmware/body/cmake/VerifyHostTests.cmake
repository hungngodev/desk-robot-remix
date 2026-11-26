# Require every host test source and every executable variant to be reachable
# by CTest. Keep explicit targets so each suite retains its own flags and fakes.
get_property(body_ctest_targets DIRECTORY PROPERTY BODY_CTEST_TARGETS)
set(body_test_sources)
foreach(target IN LISTS body_targets)
  get_target_property(target_type ${target} TYPE)
  if(target_type STREQUAL "EXECUTABLE")
    if(NOT target IN_LIST body_ctest_targets)
      message(FATAL_ERROR "Host executable ${target} has no CTest registration")
    endif()
    get_target_property(target_sources ${target} SOURCES)
    foreach(source IN LISTS target_sources)
      get_filename_component(source_path "${source}" ABSOLUTE)
      list(APPEND body_test_sources "${source_path}")
    endforeach()
  endif()
endforeach()
# Do not rely on a suffix convention or a flat test directory. A shared C++
# test helper also needs to be compiled by at least one registered executable.
file(GLOB_RECURSE discovered_body_tests CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/tests/*.cpp")
foreach(source IN LISTS discovered_body_tests)
  if(NOT source IN_LIST body_test_sources)
    message(FATAL_ERROR "Host test source ${source} has no CTest executable")
  endif()
endforeach()
