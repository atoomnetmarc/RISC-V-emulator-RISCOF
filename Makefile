# Makefile
# Wrapper that bridges the ACT4 framework clone (in ./work/src/riscv-arch-test)
# with the config and emulator in this repository.

# ACT4 framework clone (pinned to tag 4.0.0, gitignored under ./work/src/).
ACT_DIR ?= $(CURDIR)/work/src/riscv-arch-test

# Backend selection: native (default) runs the emulator directly on the host;
# avr runs it on an ATmega1284P simulated by simavr. The avr backend builds
# the AVR firmware in ../RISC-V-emulator-AVR and the simavr wrapper in
# ../RISC-V-emulator-SimAVR, and runs tests through the wrapper.
EMULATOR_BACKEND ?= native

# Native backend: emulator binary in binaries/<compiler-tag>/ under the
# emulator source repo. Override EMULATOR_TAG for other compilers (e.g. gcc-13).
EMULATOR_TAG ?= gcc,clang

# Emulator source directory (PlatformIO project). Container overrides to /emulator.
EMULATOR_SRC_DIR ?= $(abspath ../RISC-V-emulator-Native)

# Config directory layout in this repository.
CONFIG_DIR := config/cores/atoomnetmarc

# Targets that do not need a core configuration.
ifeq ($(filter report-all clean,$(MAKECMDGOALS)),)

# Core configurations are generated on demand from the ISA combination name
# (e.g. CONFIG=rve-rv32imacb_zicsr_zifencei). The generator maps the name to a
# PlatformIO environment in ../RISC-V-emulator-Native and writes the config
# directory. Existing directories are left untouched.
ifeq ($(wildcard $(CONFIG_DIR)/$(CONFIG)/config.mk),)
$(shell python3 scripts/gen_core.py $(CONFIG) >/dev/null)
endif

# Per-core settings (EMULATOR_ENV, EXCLUDE_EXTENSIONS) live in the config
# directory itself, so adding a core needs no Makefile changes. Command-line
# overrides still win over the values set here.
include $(CONFIG_DIR)/$(CONFIG)/config.mk

endif

# Backend selection happens here, after the per-core config.mk include above
# set EMULATOR_BACKEND. The avr backend runs tests through the simavr wrapper
# in ../RISC-V-emulator-SimAVR; the native backend runs the emulator built
# from ../RISC-V-emulator-Native.
ifeq ($(EMULATOR_BACKEND),avr)
EMULATOR_DIR := $(abspath ../RISC-V-emulator-SimAVR/binaries/gcc)
# The wrapper binary has a fixed name; EMULATOR_ENV selects the AVR firmware
# PlatformIO environment (ATmega1284P_ACT).
EMULATOR := $(EMULATOR_DIR)/simavr-host
else
EMULATOR_DIR := $(abspath $(EMULATOR_SRC_DIR)/binaries/$(EMULATOR_TAG))
EMULATOR := $(EMULATOR_DIR)/$(EMULATOR_ENV)
endif

# Absolute path to the config file, passed into the external framework.
CONFIG_FILE := $(abspath $(CONFIG_DIR)/$(CONFIG)/test_config.yaml)

# ELF and log directories live inside the external clone (out of this repo).
ELF_DIR := $(ACT_DIR)/work/$(CONFIG)/elfs
SUMMARY := $(ACT_DIR)/work/$(CONFIG)/summary.log

# Sail reference model binary; container overrides to /opt/sail-riscv/build/c_emulator.
SAIL_BIN ?= $(CURDIR)/work/src/sail-riscv/build/c_emulator

# UDB gem binary; ruby version directory detected dynamically (no hardcoded 3.x.y).
UDB_BIN := $(firstword $(wildcard $(ACT_DIR)/framework/src/act/data/vendor/bundle/ruby/*/bin))
UDB_GEMFILE := $(ACT_DIR)/framework/src/act/data/Gemfile

# run_test.sh wrapper: objcopy (elf2bin.sh) + emulator run. Passes the
# emulator path (and, for the avr backend, the firmware hex) through.
RUN_TEST := $(abspath scripts/run_test.sh)

# Directory for per-env run logs (report-all aggregates these). Container overrides.
LOG_DIR ?= $(CURDIR)/work/test-all

# Parallel jobs for run_tests.py. Each emulator process allocates 16 MiB of
# RAM, so keep this modest to avoid exhausting memory on large test suites.
JOBS ?= $(shell nproc)

.PHONY: elfs build run report report-all clean

# COLUMNS is forced wide because the udb progress bar crashes with
# "negative argument" when the rendered config name does not fit the
# terminal width (long ISA combination names).
elfs:
	@test -n "$(UDB_BIN)" || { echo "UDB gems not found under $(ACT_DIR)/framework/src/act/data/vendor/bundle/ruby/*/bin - run in the container or install UDB gems"; exit 1; }
	@cd "$(ACT_DIR)" && COLUMNS=250 PATH="$(SAIL_BIN):$(UDB_BIN):$$PATH" BUNDLE_GEMFILE="$(UDB_GEMFILE)" RUBYOPT="-rbundler/setup" make -j"$(JOBS)" elfs CONFIG_FILES="$(CONFIG_FILE)" $(if $(EXCLUDE_EXTENSIONS),EXCLUDE_EXTENSIONS="$(EXCLUDE_EXTENSIONS)",)

# Build the emulator binary for the selected config. The build must run in the
# project directory, so unset PLATFORMIO_WORKSPACE_DIR (the IDE sets it to /tmp).
#
# The emulator sources are prerequisites, so make rebuilds the binary whenever
# the emulator code or its build configuration changed. The RISC-V-emulator
# library is a symlinked PlatformIO dependency, so its headers count too.
EMULATOR_LIB_DIR := $(abspath ../RISC-V-emulator)
EMULATOR_DEPS := \
	$(wildcard $(EMULATOR_SRC_DIR)/src/*.c) \
	$(wildcard $(EMULATOR_SRC_DIR)/include/*.h) \
	$(wildcard $(EMULATOR_LIB_DIR)/include/*.h) \
	$(EMULATOR_SRC_DIR)/platformio.ini \
	$(EMULATOR_SRC_DIR)/platformio_isa-extension-combination_env.ini

build: $(EMULATOR)

ifeq ($(EMULATOR_BACKEND),avr)
# avr backend: build the AVR firmware (PlatformIO env from config.mk) and the
# simavr wrapper, then copy both into the SimAVR binaries directory. The
# wrapper is invoked as <wrapper> <firmware.hex> <test.bin> by run_test.sh.
AVR_SRC_DIR := $(abspath ../RISC-V-emulator-AVR)
SIMAVR_SRC_DIR := $(abspath ../RISC-V-emulator-SimAVR)
AVR_DEPS := \
	$(wildcard $(AVR_SRC_DIR)/src/*.c) \
	$(wildcard $(AVR_SRC_DIR)/include/*.h) \
	$(wildcard $(EMULATOR_LIB_DIR)/include/*.h) \
	$(AVR_SRC_DIR)/platformio.ini
SIMAVR_DEPS := \
	$(wildcard $(SIMAVR_SRC_DIR)/src/*.c) \
	$(wildcard $(SIMAVR_SRC_DIR)/include/*.h) \
	$(SIMAVR_SRC_DIR)/platformio.ini
FIRMWARE_HEX := $(EMULATOR_DIR)/$(EMULATOR_ENV).hex

$(EMULATOR): $(AVR_DEPS) $(SIMAVR_DEPS)
	@mkdir -p "$(EMULATOR_DIR)"
	@cd "$(AVR_SRC_DIR)" && env -u PLATFORMIO_WORKSPACE_DIR pio run -e "$(EMULATOR_ENV)"
	@cd "$(SIMAVR_SRC_DIR)" && env -u PLATFORMIO_WORKSPACE_DIR pio run -e simavr-host && cp ".pio/build/simavr-host/program" "$(EMULATOR).tmp" && mv -f "$(EMULATOR).tmp" "$(EMULATOR)"
	@cp "$(AVR_SRC_DIR)/hex/$(EMULATOR_ENV).hex" "$(FIRMWARE_HEX).tmp" && mv -f "$(FIRMWARE_HEX).tmp" "$(FIRMWARE_HEX)"
else
# gcc tag: the PlatformIO build (system gcc). The post-action in
# copy_binaries.py only runs on a real rebuild, so copy the binary explicitly
# to keep binaries/ in sync even when the program is up to date.
ifeq ($(EMULATOR_TAG),gcc)
$(EMULATOR): $(EMULATOR_DEPS)
	@mkdir -p "$(EMULATOR_DIR)"
	@cd "$(EMULATOR_SRC_DIR)" && env -u PLATFORMIO_WORKSPACE_DIR pio run -e "$(EMULATOR_ENV)" && cp ".pio/build/$(EMULATOR_ENV)/program" "$(EMULATOR).tmp" && mv -f "$(EMULATOR).tmp" "$(EMULATOR)"
else
# Any other tag: build with the CMake driver in RISC-V-emulator-Native, using
# the tag as the compiler name (e.g. clang, gcc-13).
$(EMULATOR):
	@cd "$(EMULATOR_SRC_DIR)" && cmake/run-matrix.py "$(EMULATOR_TAG)" --only "$(EMULATOR_ENV)"
endif
endif

# The run log lands in work/test-all/<tag>/<env>.log so report-all picks it up.
# The avr backend logs under the avr tag; the native backend logs under the compiler tag.
RUN_TAG := $(if $(filter avr,$(EMULATOR_BACKEND)),avr,$(EMULATOR_TAG))
RUN_TEST_CMD := EMULATOR=$(EMULATOR) $(if $(filter avr,$(EMULATOR_BACKEND)),EMULATOR_FIRMWARE=$(FIRMWARE_HEX) ,)$(RUN_TEST)

# run is decoupled from build; the guard gives a clear error if the binary is missing.
run:
	@test -f "$(EMULATOR)" || { echo "EMULATOR '$(EMULATOR)' not found - run 'make build' on the host first"; exit 1; }
	@mkdir -p "$(LOG_DIR)/$(RUN_TAG)"
	@cd "$(ACT_DIR)" && PATH="$(SAIL_BIN):$$PATH" ./run_tests.py -j "$(JOBS)" "$(RUN_TEST_CMD)" "$(ELF_DIR)" 2>&1 | tee "$(LOG_DIR)/$(RUN_TAG)/$(EMULATOR_ENV).log"

report:
	@cat "$(SUMMARY)"

# Aggregate all summaries from scripts/test_all.sh into a per-instruction
# failure report.
report-all:
	@python3 scripts/report_all.py "$(LOG_DIR)"

clean:
	@cd "$(ACT_DIR)" && make clean || true
	@rm -rf "$(CONFIG_DIR)"/* "$(LOG_DIR)" "$(ACT_DIR)/work"
