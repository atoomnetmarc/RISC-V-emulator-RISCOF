#!/usr/bin/env python3
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# Aggregate the per-env test summaries written by the ACT framework into an
# HTML report. The top shows a summary with the overall pass percentage; at
# 100% an easter egg appears. Below it, one collapsible section per
# instruction shows how many of its test runs succeeded: green when all
# passed, red when one or more failed. The section body lists the failing
# envs, each with a nested collapsible excerpt of the failing test log.
#
# Usage: report_all.py [log-dir]
#   log-dir defaults to work/test-all and determines which envs are included.
#   Summaries are read from work/src/riscv-arch-test/work/rve-<env>/summary.log.
#   Output: work/test-all/report.html
#
# A summary line looks like:
#   rv32i/I/I-add-00.log    RVCP-SUMMARY: TEST PASSED - Test File "I-add-00.S"
# The instruction name is the test file name without the suite prefix and the
# -00 suffix (I-add-00 -> add).

import html
import re
import sys
from collections import defaultdict
from pathlib import Path

log_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "work/test-all")
framework_dir = Path("work/src/riscv-arch-test/work")
out_path = log_dir / "report.html"

# Logs are stored per compiler tag: work/test-all/<tag>/<env>.log.
env_logs = sorted(log_dir.rglob("*.log"))
if not env_logs:
    sys.exit(f"No *.log files found in {log_dir}. Run scripts/test_all.sh first.")

line_re = re.compile(r"^(\S+?/\S+?/\S+?-\d+\.log)\s+(.+)$")
simulated_re = re.compile(r"^Simulated (\d+) CPU instructions\.$", re.MULTILINE)

# instruction -> [passed, total, env -> list of failed test log paths]
stats = defaultdict(lambda: [0, 0, defaultdict(list)])
# instruction -> sum of executed CPU instructions over all its test runs
executed = defaultdict(int)
envs = set()
missing = []

for log in env_logs:
    env = log.stem
    summary = framework_dir / f"rve-{env.lower()}" / "summary.log"
    if not summary.exists():
        missing.append(env)
        continue
    envs.add(env)
    for line in summary.read_text().splitlines():
        match = line_re.match(line.strip())
        if not match:
            continue
        log_relpath = match.group(1)
        # Instruction name: test file name without suite prefix and -NN suffix
        # (rv32i/I/I-add-00.log -> I-add -> add).
        instruction = Path(log_relpath).stem.rsplit("-", 1)[0].split("-", 1)[1]
        entry = stats[instruction]
        entry[1] += 1
        if "TEST PASSED" in match.group(2):
            entry[0] += 1
        else:
            entry[2][env].append(log_relpath)
        # Aggregate the emulator's instruction count from the test log. Logs
        # from emulator builds without the unconditional "Simulated" line
        # simply contribute nothing.
        test_log = framework_dir / f"rve-{env.lower()}" / "logs" / log_relpath
        if test_log.exists():
            m = simulated_re.search(test_log.read_text(errors="replace"))
            if m:
                executed[instruction] += int(m.group(1))

if not envs:
    sys.exit(
        f"No summaries found in {framework_dir}/rve-*/summary.log. "
        "Run scripts/test_all.sh first (make clean removes them)."
    )

LOG_TAIL_LINES = 20


def fmt_eng(n):
    # Compact "electronics" notation: 118749 -> 118k7, 1234567 -> 1M2.
    for unit, divisor in (("T", 1_000_000_000_000), ("G", 1_000_000_000), ("M", 1_000_000), ("k", 1_000)):
        if n >= divisor:
            return f"{n / divisor:.1f}".replace(".", unit)
    return str(n)


def log_excerpt(env, log_relpath):
    log_path = framework_dir / f"rve-{env.lower()}" / "logs" / log_relpath
    if not log_path.exists():
        return f"<p>Log not found: {html.escape(log_relpath)}</p>"
    lines = log_path.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:]
    text = html.escape("\n".join(lines))
    return f"<pre>{text}</pre>"


rows = []
for instruction in sorted(stats):
    passed, total, fails = stats[instruction]
    color = "#2e7d32" if passed == total else "#c62828"
    env_items = "".join(
        f"<li>{html.escape(env)}: {html.escape(log)} failed"
        f"<details><summary>log</summary>{log_excerpt(env, log)}</details></li>"
        for env, logs in sorted(fails.items())
        for log in logs
    )
    body = f"<ul>{env_items}</ul>" if env_items else "<p>All tests passed.</p>"
    count = executed.get(instruction)
    count_str = f"{fmt_eng(count)} instructions" if count else ""
    rows.append(
        f'<details><summary style="color:{color}">'
        f"{html.escape(instruction)}: {passed}/{total} succeeded"
        f"{', ' + count_str if count_str else ''}</summary>"
        f"{body}</details>"
    )

total_passed = sum(entry[0] for entry in stats.values())
total_tests = sum(entry[1] for entry in stats.values())
percent = 100 * total_passed / total_tests if total_tests else 0
all_passed = total_tests > 0 and total_passed == total_tests and not missing

# Easter egg: a hidden message that only shows up at a 100% pass rate.
registers = " ".join(f"x{i}=PASS" for i in range(32))
egg = (
    '<pre style="font-size:1.2em" title="You found the easter egg!">\n'
    "  All cores aligned.\n"
    f"  {registers}\n"
    "</pre>"
    if all_passed
    else ""
)

missing_html = (
    f'<p style="color:#c62828">No summary for {len(missing)} env(s) '
    f"(not run or failed before testing): "
    f"{html.escape(', '.join(sorted(missing)))}</p>"
    if missing
    else ""
)

html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ACT report</title>
</head>
<body>
<h1>ACT report: {len(envs)} envs, {len(stats)} instructions</h1>
<h2 style="color:{'#2e7d32' if all_passed else '#c62828'}">
Summary: {total_passed}/{total_tests} tests passed ({percent:.1f}%)<br>
<small>Total executed CPU instructions: {fmt_eng(sum(executed.values()))}</small>
</h2>
{missing_html}
{egg}
{"".join(rows)}
</body>
</html>
"""
out_path.write_text(html_doc)
print(f"Wrote {out_path} ({len(envs)} envs, {len(stats)} instructions).")
