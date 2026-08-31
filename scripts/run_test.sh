#!/bin/sh
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# run_test.sh - convert an ACT4 ELF to a raw binary and run it on the emulator.
#
# Usage (as called by run_tests.py, which appends the ELF path):
#   EMULATOR=<path> [EMULATOR_FIRMWARE=<path>] run_test.sh <elf>
#
# The emulator binary path comes from the EMULATOR environment variable (set
# by the Makefile wrapper). For the avr backend, EMULATOR_FIRMWARE holds the
# AVR firmware hex loaded by the simavr wrapper.

set -eu

ELF="${1:?usage: run_test.sh <elf>}"
EMULATOR="${EMULATOR:?usage: EMULATOR=<path> run_test.sh <elf>}"

BIN="$(mktemp "/tmp/$(basename "$ELF").XXXXXX")"
trap 'rm -f "$BIN"' EXIT

"$(dirname "$0")/elf2bin.sh" "$ELF" "$BIN"

timeout -k 5 30 "$EMULATOR" ${EMULATOR_FIRMWARE:+"$EMULATOR_FIRMWARE"} "$BIN"
