This is intended for me only. It contains code and hints on how to use [RISC-V Architectural Certification Tests](https://github.com/riscv/riscv-arch-test) tests using my [Linux implementation](https://github.com/atoomnetmarc/RISC-V-emulator-Native) of my [RISC-V emulator](https://github.com/atoomnetmarc/RISC-V-emulator).

# Install

These instructions target Arch Linux. They install the Sail reference model, the RISC-V toolchain, and the ACT4 framework dependencies.

## General tools

```bash
sudo pacman --sync --refresh
sudo pacman --sync --needed python python-pip git python-virtualenv make cmake opam z3 uv gcc shellcheck
```

## RISC-V toolchain

```bash
yay --sync --needed riscv32-gnu-toolchain-elf-bin
```

Verify:

```bash
riscv32-unknown-elf-gcc --version
riscv32-unknown-elf-objcopy --version
```

## Build tools

The script builds the Sail compiler, the RISC-V Sail model and the ACT4 framework under `./work/src/` (gitignored). It checks the system prerequisites above, then builds everything non-system. Re-running is safe; each step skips work that is already done.

```bash
./scripts/install.sh
```

Core configs are generated on demand. A config name maps to a PlatformIO environment in `../RISC-V-emulator-Native/platformio_isa-extension-combination_env.ini` (`rve-rv32imacb_zicsr_zifencei` maps to env `RV32IMACBZicsr_Zifencei`). The first `make` invocation with a new `CONFIG` runs `scripts/gen_core.py`, which writes `config/cores/atoomnetmarc/<name>/` from the templates in `config/cores/template/`. The generated directory is gitignored; `make clean` removes it. Per-core metadata (such as excluded ACT extensions) travels from the emulator's ini generator as `# act-` comment lines in the env block.

# AVR backend (simavr)

Besides the native backend, tests can run on an ATmega1284P simulated by [simavr](https://github.com/rv8-io/simavr). The avr backend builds the AVR firmware in `../RISC-V-emulator-AVR` (env `ATmega1284P_ACT`, all extensions enabled, no instruction disassembly for maximum speed) and the simavr wrapper in `../RISC-V-emulator-SimAVR` (env `simavr-host`), then runs every test through the wrapper. The RISC-V RAM is backed by a simavr peripheral with host memory, and the firmware signals pass/fail through an exit register that stops the simulation.

To debug a failing test, rebuild with the disassembly firmware (per-instruction UART disassembly, much slower):

```bash
make EMULATOR_ENV=ATmega1284P_ACT_DISASM build elfs run CONFIG=rve-avr-rv32i
```

Config names of the form `rve-avr-<isa>` select the avr backend (`rve-avr-rv32i` runs the RV32I tests on the AVR). The generated `config.mk` sets `EMULATOR_BACKEND := avr`; run logs land in `work/test-all/avr/`. simavr and avr-gcc/avr-libc must be installed (see the SimAVR and AVR project READMEs).

```bash
make elfs build run CONFIG=rve-avr-rv32i
BACKEND=avr ./scripts/test_all.sh --smoke   # every extension on the AVR
```

Since the AVR firmware is one binary with all extensions enabled, the smoke suite covers the entire AVR DUT; per-combination configs add no extra coverage.

# Usage

Generate self-checking ELFs for a config:

```bash
make elfs CONFIG=rve-rv32i
```

Build the emulator binary for a config (PlatformIO, copied to
`binaries/gcc/`; override `EMULATOR_TAG` for binaries built by
`cmake/run-matrix.py` with another compiler, e.g.
`make run CONFIG=rve-rv32i EMULATOR_TAG=clang`):

```bash
make build CONFIG=rve-rv32i
```

Run all ELFs for a config on the emulator. The run log lands in `work/test-all/<env>.log`, so `make report-all` includes it:

```bash
make run CONFIG=rve-rv32i
```

Print the summary:

```bash
make report CONFIG=rve-rv32i
```

Run the test suite for a subset of the environments in the ini (optionally filtered by regex, resumable, logs in `work/test-all/`). Envs run `nproc + 1` at a time; the pio compile is serialized with a lock. Override the parallelism with the `PARALLEL` and `JOBS` environment variables. A mode flag is required; running the script with no flag prints usage with the env count for each mode:

```bash
./scripts/test_all.sh --full              # every environment in the ini
./scripts/test_all.sh --smoke            # each extension alone + maximal-inclusion envs
./scripts/test_all.sh --smoke '^RV32IM'  # apply a regex after subset selection
EMULATOR_TAG=gcc-13 test_all.sh --full '^RV32I'   # compiler list (default: gcc,clang)
```

List the selected combinations without running them:

```bash
./scripts/test_all.sh --smoke --dry-run
PARALLEL=2 JOBS=2 ./scripts/test_all.sh --full
```

Aggregate all summaries into an HTML report. The top shows a summary with the overall pass percentage. Below it, a collapsible section per instruction shows the pass/fail count and the failing envs:

```bash
make report-all
```

Remove the ACT build outputs (including the framework's `work/` directory), the generated core configs, and the `work/test-all/` logs:

```bash
make clean
```

# License

I license my code Apache2.0, however check the files for individual licenses.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
