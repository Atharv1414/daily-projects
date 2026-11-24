.PHONY: build test tsan bench format clean
CLANG_FORMAT ?= clang-format
SOURCES := $(shell find include src apps tests bench -name '*.cpp' -o -name '*.hpp')

build:
	cmake --preset release && cmake --build --preset release

test:
	cmake --preset dev && cmake --build --preset dev && ctest --preset dev

tsan:
	CXXFLAGS=-fsanitize=thread cmake -S . -B build/tsan -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
	cmake --build build/tsan
	ctest --test-dir build/tsan --output-on-failure

bench: build
	./build/release/historian_bench

format:
	$(CLANG_FORMAT) -i $(SOURCES)

clean:
	rm -rf build
