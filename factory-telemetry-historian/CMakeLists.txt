cmake_minimum_required(VERSION 3.25)
project(historian VERSION 1.0.0 DESCRIPTION "Crash-safe, compressed time-series store for factory telemetry" LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(ENABLE_SANITIZERS "Build with AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
include(CTest)  # defines BUILD_TESTING (ON by default)

# Strict warnings for our own targets only (third-party code is included as SYSTEM).
add_library(project_options INTERFACE)
if(MSVC)
  target_compile_options(project_options INTERFACE /W4 /WX /permissive-)
else()
  target_compile_options(project_options INTERFACE
    -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion
    -Wnon-virtual-dtor -Wold-style-cast -Woverloaded-virtual -Wnull-dereference -Werror)
  if(ENABLE_SANITIZERS)
    target_compile_options(project_options INTERFACE
      -fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all)
    target_link_options(project_options INTERFACE -fsanitize=address,undefined)
  endif()
endif()

find_package(Threads REQUIRED)

add_library(historian_core
  src/analysis.cpp
  src/bitstream.cpp
  src/bytes.cpp
  src/codec.cpp
  src/csv.cpp
  src/file.cpp
  src/ingest.cpp
  src/manifest.cpp
  src/memtable.cpp
  src/segment.cpp
  src/simulator.cpp
  src/store.cpp
  src/wal.cpp
)
target_include_directories(historian_core PUBLIC include)
target_link_libraries(historian_core PUBLIC project_options Threads::Threads)

add_executable(historian apps/main.cpp)
target_link_libraries(historian PRIVATE historian_core)

option(BUILD_BENCHMARKS "Build the benchmark program" OFF)
if(BUILD_BENCHMARKS)
  add_executable(historian_bench bench/bench_main.cpp)
  target_link_libraries(historian_bench PRIVATE historian_core)
endif()

if(BUILD_TESTING)
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SYSTEM)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)

  add_executable(historian_tests tests/codec_test.cpp tests/store_test.cpp tests/recovery_test.cpp tests/ingest_test.cpp)
  target_link_libraries(historian_tests PRIVATE historian_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(historian_tests NO_PRETTY_VALUES DISCOVERY_TIMEOUT 60)
endif()
