#!/usr/bin/env python3
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# Generate a core test configuration from an ISA combination.
#
# Usage: gen_core.py <config-name>
#   e.g. gen_core.py rve-rv32imacb_zicsr_zifencei
#
# The config name maps to a PlatformIO environment in
# ../RISC-V-emulator-Native/platformio_isa-extension-combination_env.ini
# (rve-rv32imacb_zicsr_zifencei -> env RV32IMACBZicsr_Zifencei). The env block
# supplies the emulator build flags and the "# act-" metadata comments.
#
# Output: config/cores/atoomnetmarc/<config-name>/ with the files the ACT
# framework and the Makefile wrapper need.

import re
import shutil
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_DIR / "config" / "cores" / "template"
CORES_DIR = REPO_DIR / "config" / "cores" / "atoomnetmarc"
INI_FILE = REPO_DIR.parent / "RISC-V-emulator-Native" / "platformio_isa-extension-combination_env.ini"

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
    "Zbs": {
        "udb": [("Zbs", "1.0.0")],
        "sail": ["Zbs"],
        "params": [],
        "header": ["ZBS_SUPPORTED"],
    },
}


def env_name_from_config(config: str) -> str:
    # Look up the PlatformIO environment case-insensitively, so the lowercased
    # config name used by scripts/test_all.sh resolves too
    # (rve-rv32ibzicsr_zifencei -> RV32IBZicsr_Zifencei).
    isa = config.removeprefix("rve-").lower()
    for name in re.findall(r"^\[env:(\S+)\]", INI_FILE.read_text(), re.M):
        if name.lower() == isa:
            return name
    sys.exit(f"No environment matching {config!r} in {INI_FILE}")


def subsets_from_env(env: str) -> list:
    # RV32IMACBZicsr_Zifencei -> ["M", "A", "C", "B", "Zicsr", "Zifencei"]
    body = env.removeprefix("RV32I")
    named = sorted([key for key in SUBSETS if key.startswith("Z")], key=len, reverse=True)
    parts = re.split("(" + "|".join(named) + ")", body)
    subsets = []
    for part in parts:
        if part == "_":
            continue
        if part in SUBSETS:
            subsets.append(part)
        elif part:
            for letter in part:
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
            text, count = re.subn(rf'("{key}": \{{\s*"supported": )false', r"\1true", text)
            if count != 1:
                sys.exit(f"sail.json template: expected one entry for {key!r}")
    (out / "sail.json").write_text(text)


def gen_header(out: Path, subsets: list) -> None:
    text = (TEMPLATE_DIR / "rvtest_config.h").read_text().rstrip("\n")
    defines = [d for subset in subsets for d in SUBSETS[subset]["header"]]
    if defines:
        text += "\n\n" + "\n".join(f"#define {d}" for d in defines)
    (out / "rvtest_config.h").write_text(text + "\n")


def gen_config_mk(out: Path, env: str, excludes: list) -> None:
    (out / "config.mk").write_text(
        "# Per-core settings for the Makefile wrapper. Generated by scripts/gen_core.py.\n"
        f"EMULATOR_ENV := {env}\n"
        f"EXCLUDE_EXTENSIONS := {' '.join(excludes)}\n"
    )


def gen_test_config(out: Path, config: str) -> None:
    text = (TEMPLATE_DIR / "test_config.yaml").read_text()
    text = text.replace("name: rve-rv32i", f"name: {config}")
    text = text.replace("udb_config: rve-rv32i.yaml", f"udb_config: {config}.yaml")
    (out / "test_config.yaml").write_text(text)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    config = sys.argv[1]
    env = env_name_from_config(config)
    subsets = subsets_from_env(env)
    excludes = parse_ini_env(env)

    out = CORES_DIR / config
    if out.exists():
        sys.exit(f"{out} already exists")
    out.mkdir(parents=True)

    shutil.copy(TEMPLATE_DIR / "link.ld", out / "link.ld")
    shutil.copy(TEMPLATE_DIR / "rvmodel_macros.h", out / "rvmodel_macros.h")
    gen_yaml(out, config, env, subsets)
    gen_sail(out, subsets)
    gen_header(out, subsets)
    gen_config_mk(out, env, excludes)
    gen_test_config(out, config)
    print(f"Generated {out}")


if __name__ == "__main__":
    main()
