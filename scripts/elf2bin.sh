#!/bin/sh
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# elf2bin.sh - convert an ACT4 ELF to a raw binary and run it on the emulator.
#
# Usage (as called by run_tests.py, which appends the ELF path):
#   EMULATOR=<path> scripts/elf2bin.sh <elf>
#
# The emulator binary path comes from the EMULATOR environment variable
# (set by the Makefile wrapper).

set -eu

ELF="${1:?usage: elf2bin.sh <elf>}"
EMULATOR="${EMULATOR:?usage: EMULATOR=<path> elf2bin.sh <elf>}"

BIN="$(mktemp "/tmp/$(basename "$ELF").XXXXXX")"
trap 'rm -f "$BIN"' EXIT

riscv32-unknown-elf-objcopy -O binary "$ELF" "$BIN"
timeout -k 5 30 "$EMULATOR" "$BIN"
