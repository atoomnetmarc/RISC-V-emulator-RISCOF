# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# Parse a PlatformIO ini and select the ISA strings to test. Selection is
# driven by the "# isa:" and "# smoke" marker comments in each env block.

import re
from pathlib import Path


def parse_envs(ini_path: Path) -> dict:
    """Returns {env_name: block_text} for every [env:...] block."""
    text = ini_path.read_text()
    matches = list(re.finditer(r"^\[env:(\S+)\]\n(.*?)(?=^\[env:|\Z)", text, re.M | re.S))
    return {match.group(1): match.group(2) for match in matches}


def select_configs(ini_path: Path, mode: str, filter_regex: str) -> list:
    """Returns [(isa, env_name)] for every env block carrying an '# isa:'
    marker: all marked envs for --full, or the '# smoke'-marked ones for
    --smoke, then the filter regex applied to the ISA string."""
    envs = parse_envs(ini_path)
    selected = []
    for name, block in envs.items():
        marker = re.search(r"^# isa: (\S+)$", block, re.M)
        if not marker:
            continue
        if mode == "smoke" and not re.search(r"^# smoke$", block, re.M):
            continue
        if re.search(filter_regex, marker.group(1)):
            selected.append((marker.group(1), name))
    if not selected:
        raise SystemExit(f"No environments match filter {filter_regex!r} in {ini_path}")
    return sorted(selected)
