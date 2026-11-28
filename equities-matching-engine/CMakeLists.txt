cmake_minimum_required(VERSION 3.25)
project(tmatch VERSION 1.0.0 DESCRIPTION "Order book and matching engine for a UK equities venue" LANGUAGES CXX)

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

add_library(lob_core
  src/auction.cpp
  src/command.cpp
  src/exchange.cpp
  src/journal.cpp
  src/market_data.cpp
  src/order_book.cpp
  src/order_flow.cpp
  src/price_ladder.cpp
  src/risk.cpp
  src/tick_table.cpp
  src/types.cpp
)
target_include_directories(lob_core PUBLIC include)
target_link_libraries(lob_core PUBLIC project_options Threads::Threads)

add_executable(tmatch apps/main.cpp)
target_link_libraries(tmatch PRIVATE lob_core)

option(BUILD_BENCHMARKS "Build the benchmark program" OFF)
if(BUILD_BENCHMARKS)
  add_executable(tmatch_bench bench/bench_main.cpp)
  target_link_libraries(tmatch_bench PRIVATE lob_core)
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

  add_executable(lob_tests
    tests/auction_test.cpp
    tests/command_test.cpp
    tests/exchange_test.cpp
    tests/journal_test.cpp
    tests/order_book_test.cpp
    tests/property_test.cpp
    tests/spsc_ring_test.cpp
    tests/tick_table_test.cpp
  )
  target_link_libraries(lob_tests PRIVATE lob_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(lob_tests NO_PRETTY_VALUES DISCOVERY_TIMEOUT 60)
endif()
