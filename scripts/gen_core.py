#!/usr/bin/env python3
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# Generate a core test configuration from an ISA combination.
#
# Usage: gen_core.py <config-name> [--backend {native,avr}]
#   e.g. gen_core.py rve-rv32imacb_zicsr_zifencei
#
# The backend is taken from the --backend flag, or inferred from the config
# name: names of the form rve-avr-<isa> select the avr backend.
#
# The config name maps to a PlatformIO environment in
# ../RISC-V-emulator-Native/platformio_isa-extension-combination_env.ini
# (rve-rv32imacb_zicsr_zifencei -> env RV32IMACBZicsr_Zifencei). The env block
# supplies the emulator build flags and the "# act-" metadata comments.
#
# With --backend avr the config targets the simavr backend: config.mk selects
# the ATmega1284P_ACT firmware environment in ../RISC-V-emulator-AVR and
# rvmodel_macros.h halts through the AVR IO region at 0x02000000.
#
# Output: config/cores/atoomnetmarc/<config-name>/ with the files the ACT
# framework and the Makefile wrapper need.

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_DIR / "config" / "cores" / "template"
CORES_DIR = REPO_DIR / "config" / "cores" / "atoomnetmarc"
INI_FILE = REPO_DIR.parent / "RISC-V-emulator-Native" / "platformio_isa-extension-combination_env.ini"

# The avr backend runs every ISA combination through one firmware environment
# that enables all emulator extensions.
AVR_ENV = "ATmega1284P_ACT"
AVR_HALT_ADDRESS = "0x02000000"
NATIVE_HALT_ADDRESS = "0x20000000"

# Per-subset metadata. "udb" entries land in implemented_extensions of the
# architecture configuration, "sail" keys are flipped to supported in
# sail.json, "params" are appended to the yaml params section, "header" defines
# are appended to rvtest_config.h.
SUBSETS = {
    "M": {
        "udb": [("M", "2.0")],
        "sail": ["M"],
        "params": ["  # M params", "  MUTABLE_MISA_M: false"],
        "header": [],
    },
    "A": {
        "udb": [("A", "2.1.0"), ("Zaamo", "1.0.0"), ("Zalrsc", "1.0.0")],
        "sail": ["A", "Zaamo", "Zalrsc"],
        "params": [
            "  # A params",
            "  MISALIGNED_AMO: false",
            '  LRSC_RESERVATION_STRATEGY: "reserve exactly enough to cover the access"',
            "  LRSC_FAIL_ON_VA_SYNONYM: false",
            '  LRSC_MISALIGNED_BEHAVIOR: "always raise access fault"',
            "  LRSC_FAIL_ON_NON_EXACT_LRSC: false",
            "  MUTABLE_MISA_A: false",
        ],
        "header": ["ZAAMO_SUPPORTED", "ZALRSC_SUPPORTED"],
    },
    "C": {
        "udb": [("C", "2.0"), ("Zca", "1.0.0")],
        "sail": ["Zca"],
        "params": ["  # C params", "  MUTABLE_MISA_C: false"],
        "header": ["ZCA_SUPPORTED"],
    },
    "B": {
        "udb": [
            ("B", "1.0.0"),
            ("Zba", "1.0.0"),
            ("Zbb", "1.0.0"),
            ("Zbc", "1.0.0"),
            ("Zbs", "1.0.0"),
        ],
        "sail": ["B", "Zba", "Zbb", "Zbc", "Zbs"],
        "params": ["  # B params", "  MUTABLE_MISA_B: true"],
        "header": ["ZBA_SUPPORTED", "ZBB_SUPPORTED", "ZBC_SUPPORTED", "ZBS_SUPPORTED"],
    },
    # The standalone Zaamo/Zalrsc subsets carry no MUTABLE_MISA_A param: UDB
    # only allows that parameter when the A extension itself is implemented.
    "Zaamo": {
        "udb": [("Zaamo", "1.0.0")],
        "sail": ["Zaamo"],
        "params": ["  # Zaamo params", "  MISALIGNED_AMO: false"],
        "header": ["ZAAMO_SUPPORTED"],
    },
    "Zalrsc": {
        "udb": [("Zalrsc", "1.0.0")],
        "sail": ["Zalrsc"],
        "params": [
            "  # Zalrsc params",
            '  LRSC_RESERVATION_STRATEGY: "reserve exactly enough to cover the access"',
            "  LRSC_FAIL_ON_VA_SYNONYM: false",
            '  LRSC_MISALIGNED_BEHAVIOR: "always raise access fault"',
            "  LRSC_FAIL_ON_NON_EXACT_LRSC: false",
        ],
        "header": ["ZALRSC_SUPPORTED"],
    },
    "Zmmul": {
        "udb": [("Zmmul", "1.0.0")],
        "sail": ["Zmmul"],
        "params": [],
        "header": [],
    },
    "Zicsr": {"udb": [("Zicsr", "2.0")], "sail": [], "params": [], "header": []},
    "Zifencei": {"udb": [("Zifencei", "2.0.0")], "sail": [], "params": [], "header": []},
    # The standalone Zb* subsets carry no MUTABLE_MISA_B param: UDB only
    # allows that parameter when the B extension itself is implemented.
    "Zba": {
        "udb": [("Zba", "1.0.0")],
        "sail": ["Zba"],
        "params": [],
        "header": ["ZBA_SUPPORTED"],
    },
    "Zbb": {
        "udb": [("Zbb", "1.0.0")],
        "sail": ["Zbb"],
        "params": [],
        "header": ["ZBB_SUPPORTED"],
    },
    "Zbc": {
        "udb": [("Zbc", "1.0.0")],
        "sail": ["Zbc"],
        "params": [],
        "header": ["ZBC_SUPPORTED"],
    },
    "Zbkc": {
        "udb": [("Zbkc", "1.0.0")],
        "sail": ["Zbkc"],
        "params": [],
        "header": ["ZBKC_SUPPORTED"],
    },
    "Zbkb": {
        "udb": [("Zbkb", "1.0.0")],
        "sail": ["Zbkb"],
        "params": [],
        "header": ["ZBKB_SUPPORTED"],
    },
    "Zbkx": {
        "udb": [("Zbkx", "1.0.0")],
        "sail": ["Zbkx"],
        "params": [],
        "header": ["ZBKX_SUPPORTED"],
    },
    "Zcb": {
        "udb": [("Zcb", "1.0.0"), ("Zca", "1.0.0")],
        "sail": ["Zcb"],
        "params": [],
        "header": ["ZCB_SUPPORTED"],
    },
    "Zcmop": {
        "udb": [("Zcmop", "1.0.0"), ("Zca", "1.0.0")],
        "sail": ["Zcmop"],
        "params": [],
        "header": [],
    },
    "Zimop": {
        "udb": [("Zimop", "1.0.0")],
        "sail": ["Zimop"],
        "params": [],
        "header": [],
    },
    "Zicond": {
        "udb": [("Zicond", "1.0.0")],
        "sail": ["Zicond"],
        "params": [],
        "header": ["ZICOND_SUPPORTED"],
    },
    "Zicntr": {
        "udb": [("Zicntr", "2.0.0")],
        "sail": ["Zicntr"],
        "params": ["  # Zicntr params", "  TIME_CSR_IMPLEMENTED: true"],
        "header": [],
    },
    "Zihintntl": {
        "udb": [("Zihintntl", "1.0.0")],
        "sail": ["Zihintntl"],
        "params": [],
        "header": [],
    },
    "Zihintpause": {
        "udb": [("Zihintpause", "2.0.0")],
        "sail": ["Zihintpause"],
        "params": [],
        "header": [],
    },
    "Zbs": {
        "udb": [("Zbs", "1.0.0")],
        "sail": ["Zbs"],
        "params": [],
        "header": ["ZBS_SUPPORTED"],
    },
    # Not an ISA extension: the emulator is built with RVE_E_MISALIGNED=1.
    # The base template already enables misaligned load/store support, so this
    # subset only makes the env name parseable and generates a plain RV32I config.
    "Misalign": {
        "udb": [],
        "sail": [],
        "params": [],
        "header": [],
    },
}


def env_name_from_config(config: str) -> str:
    # Look up the PlatformIO environment case-insensitively, so the lowercased
    # config name used by scripts/test_all.sh resolves too
    # (rve-rv32ibzicsr_zifencei -> RV32IBZicsr_Zifencei). The avr backend uses
    # config names of the form rve-avr-<isa>; the avr- prefix selects the
    # backend and is not part of the ISA combination.
    isa = config.removeprefix("rve-").removeprefix("avr-").lower()
    for name in re.findall(r"^\[env:(\S+)\]", INI_FILE.read_text(), re.M):
        if name.lower() == isa:
            return name
    sys.exit(f"No environment matching {config!r} in {INI_FILE}")


def subsets_from_env(env: str) -> list:
    # RV32IMACBZicsr_Zifencei -> ["M", "A", "C", "B", "Zicsr", "Zifencei"]
    body = env.removeprefix("RV32I")
    named = sorted([key for key in SUBSETS if len(key) > 1], key=len, reverse=True)
    parts = re.split("(" + "|".join(named) + ")", body)
    subsets = []
    for part in parts:
        if part in SUBSETS:
            subsets.append(part)
        elif part:
            for letter in part:
                if letter == "_":
                    continue
                if letter in SUBSETS:
                    subsets.append(letter)
                else:
                    sys.exit(f"Unknown subset letter {letter!r} in {env!r}")
    return subsets


def parse_ini_env(env: str) -> list:
    # Returns the act-exclude-extensions values from the env block.
    text = INI_FILE.read_text()
    block = re.search(rf"^\[env:{re.escape(env)}\]\n(.*?)(?=^\[env:|\Z)", text, re.M | re.S)
    if not block:
        sys.exit(f"Env {env!r} not found in {INI_FILE}")
    return re.findall(r"^# act-exclude-extensions: (.+)$", block.group(1), re.M)


def gen_yaml(out: Path, config: str, env: str, subsets: list) -> None:
    text = (TEMPLATE_DIR / "core.yaml").read_text()
    text = text.replace("rv32i variant", f"{config.removeprefix('rve-')} variant")
    text = text.replace("name: rve-rv32i", f"name: {config}")
    text = text.replace(
        "description: RISC-V emulator (atoomnetmarc) - RV32I configuration DUT",
        f"description: RISC-V emulator (atoomnetmarc) - {env} configuration DUT",
    )
    # Extensions appear in ISA-string order, each followed by its derived
    # extensions (e.g. A also implies Zaamo and Zalrsc).
    ext_lines = []
    param_blocks = []
    for subset in subsets:
        meta = SUBSETS[subset]
        ext_lines += [f'  - {{ name: {name}, version: "= {version}" }}' for name, version in meta["udb"]]
        if meta["params"]:
            param_blocks.append("\n".join(meta["params"]))
    text = text.replace(
        '  - { name: Sm, version: "= 1.12.0" }',
        '  - { name: Sm, version: "= 1.12.0" }' + ("\n" + "\n".join(ext_lines) if ext_lines else ""),
    )
    if param_blocks:
        text = text.replace(
            "  PHYS_ADDR_WIDTH: 32\n\n",
            "  PHYS_ADDR_WIDTH: 32\n\n" + "\n\n".join(param_blocks) + "\n\n",
        )
    (out / f"{config}.yaml").write_text(text)


def gen_sail(out: Path, subsets: list) -> None:
    text = (TEMPLATE_DIR / "sail.json").read_text()
    for subset in subsets:
        for key in SUBSETS[subset]["sail"]:
            # The template may already list the extension as supported.
            text, count = re.subn(rf'("{key}": \{{\s*"supported": )false', r"\1true", text)
            if count == 0 and not re.search(rf'"{key}": \{{\s*"supported": true', text):
                sys.exit(f"sail.json template: expected one entry for {key!r}")
    (out / "sail.json").write_text(text)


def gen_header(out: Path, subsets: list) -> None:
    text = (TEMPLATE_DIR / "rvtest_config.h").read_text().rstrip("\n")
    defines = [d for subset in subsets for d in SUBSETS[subset]["header"]]
    if defines:
        text += "\n\n" + "\n".join(f"#define {d}" for d in defines)
    (out / "rvtest_config.h").write_text(text + "\n")


def gen_config_mk(out: Path, env: str, excludes: list, backend: str) -> None:
    lines = [
        "# Per-core settings for the Makefile wrapper. Generated by scripts/gen_core.py.\n",
    ]
    if backend == "avr":
        # The AVR firmware environment enables all extensions, so there is
        # nothing to exclude.
        lines += [f"EMULATOR_BACKEND := {backend}\n", f"EMULATOR_ENV := {env}\n"]
    else:
        lines += [
            f"EMULATOR_ENV := {env}\n",
            f"EXCLUDE_EXTENSIONS := {' '.join(excludes)}\n",
        ]
    (out / "config.mk").write_text("".join(lines))


def gen_test_config(out: Path, config: str) -> None:
    text = (TEMPLATE_DIR / "test_config.yaml").read_text()
    text = text.replace("name: rve-rv32i", f"name: {config}")
    text = text.replace("udb_config: rve-rv32i.yaml", f"udb_config: {config}.yaml")
    (out / "test_config.yaml").write_text(text)


def gen_rvmodel_macros(out: Path, backend: str) -> None:
    text = (TEMPLATE_DIR / "rvmodel_macros.h").read_text()
    if backend == "avr":
        # The AVR firmware intercepts the halt store in its IO region.
        text = text.replace(NATIVE_HALT_ADDRESS, AVR_HALT_ADDRESS)
    (out / "rvmodel_macros.h").write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--backend", choices=["native", "avr"], default=None)
    args = parser.parse_args()
    config = args.config
    backend = args.backend or (
        "avr" if config.removeprefix("rve-").startswith("avr-") else "native"
    )

    # Subsets and excludes always derive from the native environment for the
    # ISA combination; the avr backend only changes where the tests run.
    native_env = env_name_from_config(config)
    env = AVR_ENV if backend == "avr" else native_env
    subsets = subsets_from_env(native_env)
    excludes = [] if backend == "avr" else parse_ini_env(native_env)

    out = CORES_DIR / config
    if out.exists():
        sys.exit(f"{out} already exists")
    out.mkdir(parents=True)

    shutil.copy(TEMPLATE_DIR / "link.ld", out / "link.ld")
    gen_rvmodel_macros(out, backend)
    gen_yaml(out, config, env, subsets)
    gen_sail(out, subsets)
    gen_header(out, subsets)
    gen_config_mk(out, env, excludes, backend)
    gen_test_config(out, config)
    print(f"Generated {out}")


if __name__ == "__main__":
    main()
