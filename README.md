This is intended for me only. It contains code and hints on how to use [RISC-V Architectural Certification Tests](https://github.com/riscv/riscv-arch-test) tests using my [Linux implementation](https://github.com/atoomnetmarc/RISC-V-emulator-Native) of my [RISC-V emulator](https://github.com/atoomnetmarc/RISC-V-emulator).

# ACT container

The ACT framework, the Sail reference simulator and the RISC-V toolchain live
in the container image from
[`RISC-V-emulator-Tools-Container`](https://github.com/atoomnetmarc/RISC-V-emulator-Tools-Container).
Build the image once:

```bash
cd ../RISC-V-emulator-Tools-Container && podman build -t riscv-emulator-tools-container .
```

All ACT steps run inside the container through `scripts/act_container.sh`,
which resolves the image (local build wins, else `podman pull`), mounts this
repo at `/act`, the emulator repo at `/emulator` and this repo's `work/` over
the container clone's `work/` (so ELFs, summaries, run logs and `report.html`
land on the host), and exports `INI_FILE` pointing at the emulator repo. Use
`--print` to dump the exact command. `podman` is the only host dependency.

# Usage

Build the emulator binary for a config on the host (PlatformIO, copied to
`binaries/gcc/`; override `EMULATOR_TAG` for binaries built by
`cmake/run-matrix.py` with another compiler):

```bash
make build CONFIG=rve-rv32i
```

Generate the ELFs and run them on the emulator inside the container. The run
log lands in `work/test-all/<tag>/<env>.log`, so `make report-all` includes
it:

```bash
scripts/act_container.sh make elfs run CONFIG=rve-rv32i EMULATOR_SRC_DIR=/emulator
```

The first `make` invocation with a new `CONFIG` runs `scripts/gen_core.py`
(inside the container), which writes `config/cores/atoomnetmarc/<name>/` from
the templates in `config/cores/template/`. A config name maps to a PlatformIO
environment in `../RISC-V-emulator-Native/platformio_isa-extension-combination_env.ini`
(`rve-rv32imacb_zicsr_zifencei` maps to env `RV32IMACBZicsr_Zifencei`). The
generated directory is gitignored; `make clean` removes it. Per-core metadata
(such as excluded ACT extensions) travels from the emulator's ini generator as
`# act-` comment lines in the env block.

Print the summary:

```bash
scripts/act_container.sh make report CONFIG=rve-rv32i
```

Run the test suite for a subset of the environments in the ini (optionally
filtered by regex, resumable, logs in `work/test-all/`). Each env's ACT step
runs in the container (via `scripts/act_container.sh`) while the emulator
build stays on the host. Envs run `nproc` at a time; the pio compile is
serialized with a lock. Override the parallelism with the `PARALLEL` and
`JOBS` environment variables. A mode flag is required; running the script
with no flag prints usage with the env count for each mode:

```bash
./scripts/test_all.sh --full              # every environment in the ini
./scripts/test_all.sh --smoke             # each extension alone + maximal-inclusion envs
./scripts/test_all.sh --smoke '^RV32IM'   # apply a regex after subset selection
EMULATOR_TAG=gcc-13 ./scripts/test_all.sh --full '^RV32I'   # compiler list (default: gcc,clang)
```

List the selected combinations without running them:

```bash
./scripts/test_all.sh --smoke --dry-run
PARALLEL=2 JOBS=2 ./scripts/test_all.sh --full
```

Aggregate all summaries into an HTML report (in the container; the report
lands in `work/test-all/report.html` on the host). The top shows a summary
with the overall pass percentage. Below it, a collapsible section per
instruction shows the pass/fail count and the failing envs:

```bash
scripts/act_container.sh make report-all
```

Remove the ACT build outputs (including the framework's `work/` directory),
the generated core configs, and the `work/test-all/` logs:

```bash
scripts/act_container.sh make clean
```

# AVR backend (simavr) — deferred

Besides the native backend, tests can run on an ATmega1284P simulated by
[simavr](https://github.com/rv8-io/simavr). The avr backend currently requires
host-side ACT and PlatformIO tooling that the container image does not provide;
supporting it through the container is a known follow-up. Until then the notes
below describe the host flow.

The avr backend builds the AVR firmware in `../RISC-V-emulator-AVR` (env
`ATmega1284P_ACT`, all extensions enabled, no instruction disassembly for
maximum speed) and the simavr wrapper in `../RISC-V-emulator-SimAVR` (env
`simavr-host`), then runs every test through the wrapper. The RISC-V RAM is
backed by a simavr peripheral with host memory, and the firmware signals
pass/fail through an exit register that stops the simulation.

To debug a failing test, rebuild with the disassembly firmware (per-instruction
UART disassembly, much slower):

```bash
make EMULATOR_ENV=ATmega1284P_ACT_DISASM build elfs run CONFIG=rve-avr-rv32i
```

Config names of the form `rve-avr-<isa>` select the avr backend (`rve-avr-rv32i`
runs the RV32I tests on the AVR). The generated `config.mk` sets
`EMULATOR_BACKEND := avr`; run logs land in `work/test-all/avr/`. simavr and
avr-gcc/avr-libc must be installed (see the SimAVR and AVR project READMEs).

```bash
BACKEND=avr ./scripts/test_all.sh --smoke   # every extension on the AVR
```

Since the AVR firmware is one binary with all extensions enabled, the smoke
suite covers the entire AVR DUT; per-combination configs add no extra coverage.

# License

I license my code Apache2.0, however check the files for individual licenses.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
