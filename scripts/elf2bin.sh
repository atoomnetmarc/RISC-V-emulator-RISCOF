#!/bin/sh
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# elf2bin.sh - convert an ACT4 ELF to a raw binary.
#
# Usage:
#   elf2bin.sh <elf> <bin>

set -eu

ELF="${1:?usage: elf2bin.sh <elf> <bin>}"
BIN="${2:?usage: elf2bin.sh <elf> <bin>}"

riscv32-unknown-elf-objcopy -O binary "$ELF" "$BIN"
