# Makefile
# Wrapper that bridges the ACT4 framework clone (in ./work/src/riscv-arch-test)
# with the config and emulator in this repository.

# ACT4 framework clone (pinned to tag 4.0.0, gitignored under ./work/src/).
ACT_DIR ?= $(CURDIR)/work/src/riscv-arch-test

# Emulator binary (lives in the sibling RISC-V-emulator-Native repository).
# Absolute path: run_tests.py runs from inside $(ACT_DIR).
# Each config maps to a PlatformIO env binary in binaries/<compiler-tag>/.
# The native PlatformIO build always uses the default gcc toolchain; override
# EMULATOR_TAG to select binaries built by cmake/run-matrix.py with another
# compiler (e.g. EMULATOR_TAG=gcc-13).
EMULATOR_TAG ?= gcc,clang
EMULATOR_DIR := $(abspath ../RISC-V-emulator-Native/binaries/$(EMULATOR_TAG))

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
EMULATOR := $(EMULATOR_DIR)/$(EMULATOR_ENV)

# Absolute path to the config file, passed into the external framework.
CONFIG_FILE := $(abspath $(CONFIG_DIR)/$(CONFIG)/test_config.yaml)

# ELF and log directories live inside the external clone (out of this repo).
ELF_DIR := $(ACT_DIR)/work/$(CONFIG)/elfs
SUMMARY := $(ACT_DIR)/work/$(CONFIG)/summary.log

# Sail reference model binary, built under ./work/src/sail-riscv. The framework
# resolves ref_model_exe via PATH, so prepend its build directory.
SAIL_BIN := $(CURDIR)/work/src/sail-riscv/build/c_emulator

# UDB gem binary, installed locally under the framework's data dir. The wrapper
# needs the bundler environment to find the gem in vendor/bundle.
UDB_BIN := $(ACT_DIR)/framework/src/act/data/vendor/bundle/ruby/3.4.0/bin
UDB_GEMFILE := $(ACT_DIR)/framework/src/act/data/Gemfile

# elf2bin.sh wrapper: objcopy + emulator. Passes the emulator path through.
ELF2BIN := $(abspath scripts/elf2bin.sh)

# mise paths. The ACT framework Makefile requires mise (or bare ruby/uv) on
# PATH. Prepend the mise binary and shims directories so make targets work in
# a shell without an activated mise environment.
MISE_PATH := $(HOME)/.local/share/mise/shims:$(HOME)/.local/bin

# Parallel jobs for run_tests.py. Each emulator process allocates 16 MiB of
# RAM, so keep this modest to avoid exhausting memory on large test suites.
JOBS ?= $(shell nproc)

.PHONY: elfs build run report clean

# COLUMNS is forced wide because the udb progress bar crashes with
# "negative argument" when the rendered config name does not fit the
# terminal width (long ISA combination names).
elfs:
	@cd "$(ACT_DIR)" && COLUMNS=250 PATH="$(MISE_PATH):$(SAIL_BIN):$(UDB_BIN):$$PATH" BUNDLE_GEMFILE="$(UDB_GEMFILE)" RUBYOPT="-rbundler/setup" make -j$$(nproc) elfs CONFIG_FILES="$(CONFIG_FILE)" $(if $(EXCLUDE_EXTENSIONS),EXCLUDE_EXTENSIONS="$(EXCLUDE_EXTENSIONS)",)

# Build the emulator binary for the selected config. The build must run in the
# project directory, so unset PLATFORMIO_WORKSPACE_DIR (the IDE sets it to /tmp).
#
# The emulator sources are prerequisites, so make rebuilds the binary whenever
# the emulator code or its build configuration changed. The RISC-V-emulator
# library is a symlinked PlatformIO dependency, so its headers count too.
EMULATOR_SRC_DIR := $(abspath ../RISC-V-emulator-Native)
EMULATOR_LIB_DIR := $(abspath ../RISC-V-emulator)
EMULATOR_DEPS := \
	$(wildcard $(EMULATOR_SRC_DIR)/src/*.c) \
	$(wildcard $(EMULATOR_SRC_DIR)/include/*.h) \
	$(wildcard $(EMULATOR_LIB_DIR)/include/*.h) \
	$(EMULATOR_SRC_DIR)/platformio.ini \
	$(EMULATOR_SRC_DIR)/platformio_isa-extension-combination_env.ini

build: $(EMULATOR)

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

# The run log lands in work/test-all/<tag>/<env>.log so report-all picks it up
# the same way as the logs written by scripts/test_all.sh.
run: build
	@mkdir -p work/test-all/$(EMULATOR_TAG)
	@cd "$(ACT_DIR)" && PATH="$(MISE_PATH):$(SAIL_BIN):$$PATH" ./run_tests.py -j "$(JOBS)" "EMULATOR=$(EMULATOR) $(ELF2BIN)" "$(ELF_DIR)" 2>&1 | tee "$(CURDIR)/work/test-all/$(EMULATOR_TAG)/$(EMULATOR_ENV).log"

report:
	@cat "$(SUMMARY)"

# Aggregate all summaries from scripts/test_all.sh into a per-instruction
# failure report.
report-all:
	@python3 scripts/report_all.py

clean:
	@cd "$(ACT_DIR)" && PATH="$(MISE_PATH):$$PATH" make clean || true
	@rm -rf "$(CONFIG_DIR)"/* work/test-all "$(ACT_DIR)/work"
