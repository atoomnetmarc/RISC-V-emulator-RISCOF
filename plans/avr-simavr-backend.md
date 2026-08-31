# Plan: Run ACT tests on a simulated AVR via simavr

## Goal

Run the RISC-V Architectural Certification Tests (ACT) on the RISC-V
emulator compiled for AVR, executing inside simavr. This validates that the
emulator library builds and runs correctly on the AVR architecture, not
just natively.

## Architecture overview

```
ACT framework (run_tests.py)
  |
  | calls EMULATOR <bin> via elf2bin.sh (unchanged; same script for
  |   native and avr backends)
  v
simavr wrapper (C program, links libsimavr)          [element 4]
  |-- fopen/fread the test bin into a malloc'd buffer
  |-- create AVR core (atmega1284p)
  |-- load AVR firmware ELF/HEX (ATmega1284P_ACT)
  |-- attach VPI peripheral (16 MiB RAM buffer + EXIT watch at IO 0x39)
  |-- register UART IRQ hook -> putchar to stdout
  |-- run until halt or 60 s timeout
  |-- exit 0 (pass) or 1 (fail)
  v
simavr (simulates the AVR)
  |
  | runs AVR firmware (src/main.c + src/act.c)       [element 1]
  v
AVR firmware (RiscvEmulatorLoop)
  |-- RiscvEmulatorLoad/Store route 0x80000000 to VPI IO registers
  |   (24-bit offset via 0x31/0x32/0x33 + DATA 0x34, auto-increment)
  |-- RiscvEmulatorStore routes 0x10000000 to AVR UART (simavr captures)
  |-- RiscvEmulatorStore intercepts the halt-region store (0x02000000),
  |   prints result + instruction count, writes the 8-bit exit status to
  |   VPI_EXIT (IO 0x39; stops simavr)
  |-- instruction counter (verbose only, no firmware-side limit)
  v
RISC-V emulator library (same as Native, compiled for AVR)
```

The work splits into five elements:

1. **AVR firmware** (../RISC-V-emulator-AVR project) — DONE
2. **ACT framework integration** (gen_core.py, Makefile, this project) — open
3. **VPI peripheral contract** (shared firmware/wrapper interface) — firmware side DONE
4. **simavr wrapper + VPI peripheral** (../RISC-V-emulator-SimAVR project) — DONE, see
   ../RISC-V-emulator-SimAVR/plans/avr-simavr-act.md
5. **Validation** (single config, then full suite) — open

---

## Element 1: AVR firmware (../RISC-V-emulator-AVR project) — DONE

### Design decisions

- **What to simulate** (Q1): custom AVR firmware + simavr. We simulate the
  AVR itself, not the external SPI PSRAM and SPI flash chips. The goal is
  to prove the emulator library works on AVR, not to model the full demo
  board.
- **Where RISC-V memory lives** (Q2): a simavr VPI peripheral backs the
  RISC-V RAM with host memory (malloc). The ATmega2560 has no XMEM; the
  ATmega2561 has XMEM (64 KiB max) but simavr does not model XMEM for any
  chip. Writing an XMEM model is the same effort as a VPI peripheral with
  a smaller size limit. So: VPI peripheral, unlimited size.
- **Address layout** (Q3): do not split. Put everything at 0x80000000 in
  VPI-backed RAM, skip PROGMEM entirely. Use the existing link.ld
  (everything at 0x80000000), the existing single-blob objcopy -O binary,
  and the smallest diff from the Native emulator. There is no SRAM
  constraint forcing code into PROGMEM because the VPI buffer is unlimited
  host memory.
- **Memory size constraint** (Q4, measured across all 11624 ACT ELFs):
  - Emulator state (RiscvEmulatorState_t): 224 bytes. Negligible.
  - Code: max 112 KiB, avg 13 KiB. 100% fits in 256 KiB flash.
  - Data: max 34 KiB, avg 15 KiB. Only 44% fits in 8 KiB SRAM.
  - Conclusion: 8 KiB AVR SRAM is not enough; the VPI peripheral solves
    this by backing RISC-V RAM with unlimited host memory.
- **Halt-region robustness** (added after the first simavr-host test run):
  the first wrapper run showed the test binary halting at the NATIVE halt
  address (a store into the ROM region) instead of the AVR halt address
  0x02000000 — the firmware then hit the ROM-write trap without writing
  VPI_EXIT, so the wrapper read 0xFF and reported failure. Root cause: the
  AVR-specific rvmodel_macros.h (element 2, gen_core.py --backend avr) has
  not been generated yet. Defensive firmware fix (implemented): in ACT mode
  nothing is mapped in the ROM region, so act_halt() also treats any store
  at address >= ROM_ORIGIN as a halt attempt (reads the result value,
  prints it, writes VPI_EXIT). The proper fix remains element 2: generate
  the AVR rvmodel_macros.h with RVMODEL_HALT_ADDRESS = 0x02000000.
- **Halt and pass/fail signaling** (Q5): the RISC-V halt address stays a
  RISC-V address (the halt region the test writes its result to,
  123456789 = pass, 1 = fail). simavr cannot watch RISC-V addresses, so
  detection happens in the AVR firmware: the RVE_AVR_E_ACT path intercepts
  the RISC-V store to the halt region (IO_ORIGIN 0x02000000), compares the
  value with 123456789, and writes an 8-bit exit status to the VPI EXIT
  register (0x39): 0x00 = pass, 0x01 = fail. The VPI then stops simavr via
  avr->state = cpu_Done and the wrapper exits 0 (pass) or 1 (fail).
  run_tests.py checks BOTH the exit code AND the "RVCP-SUMMARY: TEST
  PASSED" line on stdout (printed by the RISC-V test binary over UART). On
  fail, the firmware prints the raw 32-bit result value over UART for
  debugging. The per-core rvmodel_macros.h gets a one-line address change
  for RVMODEL_HALT_PASS and RVMODEL_HALT_FAIL.
- **Timeout** (Q12): no firmware-side instruction limit; the firmware just
  runs RiscvEmulatorLoop forever until the halt store or the wrapper
  timeout (60 s, plus the existing timeout 30 from elf2bin.sh as outer
  guard).

### Implementation (all done, in the AVR project)

- **src/act.c + include/act.h** — the ACT module (compiled to nothing in
  demo builds):
  - VPI register definitions (see element 3).
  - `act_load`/`act_store`: 24-bit offset + DATA auto-increment.
  - `act_halt`: halt intercept, verbose print of result + instruction
    count, VPI_EXIT write, stop.
  - Instruction counter (`act_count_instruction`), printed at halt.
  - `act_init()`: initialises VPI_EXIT to 0xFF (undefined exit) and prints
    the ACT banner.
- **include/RiscvEmulatorImplementationSpecific.h** — `#ifdef RVE_AVR_E_ACT`
  path delegating RAM routing to act_load/act_store and the IO halt store
  to act_halt. Demo path (psram/flash) unchanged.
- **src/main.c** — one shared `main()`:
  - Demo peripheral init (SPI/PSRAM/flash/FatFs/TFT) guarded by
    `#if (RVE_AVR_E_ACT == 0)`.
  - In ACT mode: `act_init()`, and after `RiscvEmulatorInit` the PC is
    overridden to RAM_ORIGIN. Note: `RiscvEmulatorInit` always sets
    PC = ROM_ORIGIN (unreadable in ACT mode — same fix as the Native
    emulator) and its second argument is `ram_length` for the stack
    pointer, NOT the start PC.
- **include/defines.h**:
  - ACT mode forces `RVE_AVR_E_FATFS/TFT` to 0 and `RVE_AVR_E_VERBOSE` to 1.
  - `RVE_AVR_E_START_ADDRESS`: RAM_ORIGIN for ACT, 0x800000 for the demo.
  - `RVE_AVR_E_RAM_LENGTH`: 0x1000000 (16 MiB VPI buffer) for ACT,
    0x800000 (8 MiB PSRAM) for the demo.
- **platformio.ini** — new `[env:ATmega1284P_ACT]` with all RISC-V
  extension flags enabled plus `-D RVE_AVR_E_ACT=1`; builds src/main.c +
  src/act.c (no build_src_filter needed).
- **Build status**: ACT env and largest demo env both build successfully
  (ACT: 19.7 KiB flash, 298 B SRAM).
- **Verbose output**: ACT banner at startup, "Halt: result 0x... after N
  instructions" at halt.

---

## Element 2: ACT framework integration (this project) — OPEN

- **Makefile** (Q11): new EMULATOR_BACKEND variable (native default, avr
  opt-in). The Makefile branches on it to build the AVR firmware + simavr
  wrapper and set EMULATOR to the wrapper path. elf2bin.sh is used
  unchanged for both backends: it just runs EMULATOR <bin>. Per-core
  config.mk sets EMULATOR_BACKEND := avr and EMULATOR_ENV :=
  ATmega1284P_ACT.
- **Per-core config generation** (Q13): gen_core.py gets an --backend avr
  flag that writes EMULATOR_BACKEND := avr and EMULATOR_ENV :=
  ATmega1284P_ACT into config.mk, and writes the AVR-specific
  rvmodel_macros.h (halt at 0x02000000). link.ld stays the same
  (everything at 0x80000000).
- **Sail reference model** (Q14): unchanged. The ACT framework handles the
  Sail reference model, signature comparison, and pass/fail reporting. The
  AVR path is a drop-in DUT replacement; only the EMULATOR binary changes.

---

## Element 3: VPI peripheral contract (firmware/wrapper interface) — firmware side DONE

Register a custom simavr IO module with five AVR IO registers. The AVR
firmware writes the 24-bit RISC-V RAM offset to ADDR_LO/ADDR_MID/ADDR_HI,
then reads or writes DATA with auto-increment. Standard simavr peripheral
pattern (like the i2c_eeprom example). A 4-byte load is 1 address-set + 4
data reads = 5 AVR IO operations, vs hundreds of SPI cycles in the real
firmware.

IO addresses (verified free in BOTH avr-libc iom1284p.h and the simavr
atmega1284p core; all reachable with 1-cycle in/out instructions via
_SFR_IO8, since they are < 0x60):

| Register | IO addr | Function |
|----------|---------|----------|
| VPI_ADDR_LO  | 0x31 | bits 0-7 of the 24-bit RAM offset |
| VPI_ADDR_MID | 0x32 | bits 8-15 |
| VPI_ADDR_HI  | 0x33 | bits 16-23 |
| VPI_DATA     | 0x34 | byte read/write, auto-increments the offset |
| VPI_EXIT     | 0x39 | 8-bit exit status: 0x00 = pass, 0x01 = fail, 0xFF = undefined (initialised by the firmware at startup; no halt store happened); a write stops simavr (cpu_Done) |

24-bit addressing (not 16-bit) because the largest ACT test binary is
139392 bytes (~136 KiB) > 64 KiB. The host buffer is 16 MiB
(RAM_LENGTH 0x1000000, same as the Native emulator's memory.h), malloc'd
by the wrapper, binary loaded at offset 0 (byte 0 = RISC-V address
0x80000000). The AVR firmware computes the offset as
address - 0x80000000 and writes its three bytes little-endian to
ADDR_LO/ADDR_MID/ADDR_HI.

Firmware access pattern (implemented in src/act.c, RVE_AVR_E_ACT):

```c
#define VPI_ADDR_LO  _SFR_IO8(0x11)  // IO 0x31 = mem 0x31; _SFR_IO8 takes IO addr (mem-0x20)
#define VPI_ADDR_MID _SFR_IO8(0x12)
#define VPI_ADDR_HI  _SFR_IO8(0x13)
#define VPI_DATA     _SFR_IO8(0x14)
#define VPI_EXIT     _SFR_IO8(0x19)
```

Note: _SFR_IO8(n) maps to memory address n + 0x20, so IO address 0x31 is
_SFR_IO8(0x11). The memory addresses 0x31/0x32/0x33/0x34/0x39 are the
authoritative ones.

---

## Element 4: simavr wrapper + VPI peripheral (../RISC-V-emulator-SimAVR project) — DONE

Details in ../RISC-V-emulator-SimAVR/plans/avr-simavr-act.md. Implemented:

- **simavr wrapper** (src/main.c): creates an atmega1284p core, loads AVR
  firmware (ELF or Intel HEX via sim_setup_firmware, since the system
  libsimavr is built without libelf), taps the UART0 TX IRQ and prints
  every transmitted byte to stdout, and runs until
  cpu_Sleeping/cpu_Crashed/cpu_Done. Prints cycle statistics to stderr.
  This covers the UART output capture decision (Q9) and Q8.
- **VPI peripheral** (src/vpi.h): 16 MiB RAM buffer, register protocol
  exactly matching element 3 (0x31/0x32/0x33/0x34/0x39), EXIT watch that
  stops simavr on write and reports the exit status, including 0xFF =
  undefined handling.
- **Timeout** (Q12): 60 second execution timeout enforced by the wrapper.
- **Build system**: PlatformIO [env:simavr-host] (native platform) links
  against the system libsimavr via pkg-config. copy_binaries.py copies the
  built binary to binaries/gcc/simavr-host, so the ACT framework can find
  the EMULATOR binary there.
- **Verified end-to-end** with a first ACT test run (Zimop-mop.r.30-00.S):
  UART output captured, summary line printed, halt store intercepted,
  VPI exit status read. That run exposed the ROM-region halt issue fixed
  in element 1.

---

## Element 5: Validation — partially done

1. ~~Test with a single config (e.g. rve-rv32i) and a few tests~~ DONE:
   verified end-to-end with ~40 ACT tests running through the simavr
   wrapper (including Zimop-mop.r.30-00.S; that run exposed the ROM-region
   halt issue fixed in element 1).
2. Run the full suite and measure total runtime.
3. Measure simavr throughput (not yet measured precisely; a trivial blink
   program ran for 3 seconds without issue).

---

## Discoveries

### simavr vs qemu-system-avr

- simavr (1.8-1) has a clean peripheral-attachment API (IRQ hooks, custom
  IO modules). It ships parts/ examples (i2c_eeprom, ssd1306, hc595, etc.).
  It can model virtual SPI slaves via custom C parts.
- qemu-system-avr (11.1.0) is far more limited. Only 3 generic devices
  (loader, uefi-vars). No SPI flash, no SPI RAM, no memory devices. AVR
  machines are hardcoded board models. Cannot add custom SPI slaves without
  writing and recompiling C qemu device code.
- simavr CLI binary on Arch does not support ELF loading (only HEX). The
  wrapper links libsimavr directly and can use the ELF or HEX API.

### XMEM

- ATmega2560: no XMEM peripheral at all (XMCRA/XMCRB not in iom2560.h).
- ATmega2561: has XMEM (XMCRA/XMCRB in iomxx0_1.h, 64 KiB max).
- simavr: does not model XMEM for any chip. No XMEM code in the simavr
  source.

### Build dependencies (all already installed)

- avr-gcc 16.1.0
- avr-libc 2.3.2-3 (libraries in /usr/lib/avr/lib/avr51/ for ATmega1284P)
- simavr 1.8-1 (libsimavr.so + headers in /usr/include/simavr/)
- PlatformIO 6.1.19 with atmelavr 5.1.0
- No new system dependencies needed. install.sh needs no changes.

### ACT test sizes (11624 ELFs measured)

- Code: max 112 KiB, avg 13 KiB. Fits in 256 KiB flash.
- Data: max 34 KiB, avg 15 KiB. Does not fit in 8 KiB SRAM (44% fit).
- RISC-V instruction counts per test: 500-16400 for passing tests. Most
  tests run in under 4000 RISC-V instructions. The Native emulator's 100M
  safety net is never hit by passing tests.

### RiscvEmulatorInit semantics (gotcha)

`RiscvEmulatorInit(state, ram_length)` uses its second argument as the RAM
size for the stack pointer (`sp = RAM_ORIGIN + ram_length`) and always sets
PC = ROM_ORIGIN. It does NOT take a start PC. The ACT firmware must pass
the VPI RAM length (16 MiB) and override programcounter/programcounternext
to RAM_ORIGIN afterwards.
