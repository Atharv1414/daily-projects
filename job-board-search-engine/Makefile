.PHONY: build test bench demo format format-check clean
CLANG_FORMAT ?= clang-format
SOURCES := $(shell find include src apps tests bench -name '*.cpp' -o -name '*.hpp')

build:
	cmake --preset release && cmake --build --preset release

test:
	cmake --preset dev && cmake --build --preset dev && ctest --preset dev

bench: build
	./build/release/jobsearch_bench 100000

demo: build
	./build/release/jobsearch demo

format:
	$(CLANG_FORMAT) -i $(SOURCES)

format-check:
	$(CLANG_FORMAT) --dry-run --Werror $(SOURCES)

clean:
	rm -rf build jobs-index
