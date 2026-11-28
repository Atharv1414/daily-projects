.PHONY: build test bench demo simulate format format-check clean
CLANG_FORMAT ?= /tmp/daily-projects-venv/bin/clang-format
SOURCES := $(shell find include src apps tests bench -name '*.cpp' -o -name '*.hpp')

build:
	cmake --preset release && cmake --build --preset release

test:
	cmake --preset dev && cmake --build --preset dev && ctest --preset dev

bench:
	cmake --preset release -DBUILD_BENCHMARKS=ON && cmake --build --preset release
	./build/release/tmatch_bench 2000000

demo: build
	./build/release/tmatch demo

simulate: build
	./build/release/tmatch simulate --orders 1000000 --seed 42 --journal session.journal
	./build/release/tmatch replay --journal session.journal

format:
	$(CLANG_FORMAT) -i $(SOURCES)

format-check:
	$(CLANG_FORMAT) --dry-run --Werror $(SOURCES)

clean:
	rm -rf build session.journal
