cmake_minimum_required(VERSION 3.25)
project(jobsearch VERSION 1.0.0 DESCRIPTION "Search engine for UK job adverts" LANGUAGES CXX)

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

add_library(jobsearch_core
  src/codec.cpp
  src/corpus.cpp
  src/index.cpp
  src/postings.cpp
  src/query.cpp
  src/searcher.cpp
  src/segment.cpp
  src/text.cpp
)
target_include_directories(jobsearch_core PUBLIC include)
target_link_libraries(jobsearch_core PUBLIC project_options Threads::Threads)

add_executable(jobsearch apps/main.cpp)
target_link_libraries(jobsearch PRIVATE jobsearch_core)

option(BUILD_BENCHMARKS "Build the benchmark program" OFF)
if(BUILD_BENCHMARKS)
  add_executable(jobsearch_bench bench/bench_main.cpp)
  target_link_libraries(jobsearch_bench PRIVATE jobsearch_core)
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

  add_executable(jobsearch_tests
    tests/text_test.cpp
    tests/postings_test.cpp
    tests/query_test.cpp
    tests/segment_test.cpp
    tests/index_test.cpp
    tests/searcher_test.cpp
  )
  target_link_libraries(jobsearch_tests PRIVATE jobsearch_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(jobsearch_tests NO_PRETTY_VALUES DISCOVERY_TIMEOUT 60)
endif()
