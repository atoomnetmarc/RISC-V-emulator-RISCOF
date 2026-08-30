#!/usr/bin/env bash
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# Run the ACT test suite for a subset of the PlatformIO environments in the
# emulator's platformio_isa-extension-combination_env.ini.
#
# Usage: test_all.sh --full  [--dry-run] [filter-regex]
#        test_all.sh --smoke [--dry-run] [filter-regex]
#
#   --full    run every environment in the ini.
#   --smoke   run the environments marked "# smoke" in the ini. The generator
#             (generate-isa-extension-combination.py) marks: in default mode
#             every env of the covering array; in --full mode each extension
#             alone plus every maximal legal combination.
#   --dry-run list the selected environments without running them.
#   filter    a regex applied after subset selection, e.g. '^RV32IM'.
#
# EMULATOR_TAG (env var) selects the compiler tag: gcc (default, PlatformIO
# build) or a compiler built via cmake/run-matrix.py. A comma-separated list
# runs the selection once per tag, e.g.
#   EMULATOR_TAG=clang test_all.sh --smoke
#   EMULATOR_TAG=clang,gcc-13 test_all.sh --full '^RV32I'
#
# Envs run in parallel, $(nproc) + 1 at a time. Each env's run_tests.py also
# uses $(nproc) + 1 jobs; there is plenty of memory for the oversubscription.
# The pio build (make build) is serialized with flock so only one compile
# happens at a time. Override both counts with the PARALLEL and JOBS
# environment variables, e.g. PARALLEL=2 JOBS=2 test_all.sh on a low-memory
# machine. Per-env summaries land in work/test-all/<tag>/<env>.log. An env
# counts as done only if its log ends with the run_tests.py success line
# ("RESULT: All N tests passed."); anything else (build failure, test
# failure, interruption) is re-run on the next invocation.

set -u

INI=../RISC-V-emulator-Native/platformio_isa-extension-combination_env.ini
PARALLEL=${PARALLEL:-$(( $(nproc) + 1 ))}
JOBS=${JOBS:-$PARALLEL}

# Parse flags. --full or --smoke is required; --dry-run is optional.
mode=
dry_run=0
while [ $# -gt 0 ]; do
  case "$1" in
    --full)  mode=full;  shift ;;
    --smoke) mode=smoke; shift ;;
    --dry-run) dry_run=1; shift ;;
    --*) echo "Unknown option: $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
FILTER=${1:-.}

if [ -z "$mode" ]; then
  all=$(grep -oP '^\[env:\K[^\]]+' "$INI" | wc -l)
  smoke=$(grep -c '^# smoke' "$INI")
  cat >&2 <<EOF
Usage: $0 --full  [--dry-run] [filter-regex]
       $0 --smoke [--dry-run] [filter-regex]

  --full    run every environment in the ini ($all envs).
  --smoke   run the environments marked "# smoke" in the ini ($smoke envs):
            each extension alone plus the maximal combinations.
  --dry-run list the selected environments without running them.
  filter    a regex applied after subset selection, e.g. '^RV32IM'.

  EMULATOR_TAG=gcc (default) or a compiler built via cmake/run-matrix.py;
  comma-separated lists run the selection once per tag, e.g.
  EMULATOR_TAG=clang,gcc-13.
EOF
  exit 2
fi

# Select the env list for the chosen mode, then apply the filter regex.
if [ "$mode" = full ]; then
  envs=$(grep -oP '^\[env:\K[^\]]+' "$INI")
else
  # Select envs marked with "# smoke" by the generator script.
  envs=$(awk '
    /^\[env:/ {
      if (env != "" && smoke) print env
      env = $0; sub(/^\[env:/, "", env); sub(/\]$/, "", env); smoke = 0
    }
    /^# smoke/ { smoke = 1 }
    END { if (env != "" && smoke) print env }
  ' "$INI")
fi
envs=$(echo "$envs" | grep -P "$FILTER")
total=$(echo "$envs" | grep -c .)

run_one() {
  local i=$1 env=$2 config log
  log="$OUTDIR/$env.log"
  if grep -q 'RESULT: All .* tests passed\.' "$log" 2>/dev/null; then
    echo "[$i/$total] $env: skip (passed)"
    return 0
  fi
  config=$(grep -A1 "^\[env:$env\]" "$INI" | grep -oP '^# act-config: \K.+')
  # Serialize the pio compile; the lock is only held for the build.
  if ! flock "$OUTDIR/pio.lock" make build "CONFIG=$config" >> "$log" 2>&1; then
    echo "[$i/$total] $env: BUILD FAILED (see $log)"
    return 1
  fi
  echo "[$i/$total] $env: running"
  if make elfs run "CONFIG=$config" "JOBS=$JOBS" >> "$log" 2>&1; then
    echo "[$i/$total] $env: $(tail -1 "$log")"
  else
    echo "[$i/$total] $env: FAILED (see $log)"
  fi
}

if [ "$dry_run" = 1 ]; then
  for tag in $(echo "${EMULATOR_TAG:-gcc}" | tr ',' ' '); do
    OUTDIR=work/test-all/$tag
    echo "=== Compiler tag: $tag ==="
    i=0
    for env in $envs; do
      i=$((i + 1))
      log="$OUTDIR/$env.log"
      if grep -q 'RESULT: All .* tests passed\.' "$log" 2>/dev/null; then
        echo "[$i/$total] $env: skip (passed)"
      else
        echo "[$i/$total] $env: queued"
      fi
    done
  done
  echo
  echo "Dry run: $total envs selected per tag."
  exit 0
fi

export -f run_one
export INI JOBS total

start=$SECONDS
overall_failed=0
# Comma-separated tags: run the whole selection once per tag. Logs are kept
# per tag in work/test-all/<tag>/.
for tag in $(echo "${EMULATOR_TAG:-gcc}" | tr ',' ' '); do
  OUTDIR=work/test-all/$tag
  mkdir -p "$OUTDIR"
  export OUTDIR EMULATOR_TAG=$tag
  echo "=== Compiler tag: $tag ==="
  # nl numbers the envs so run_one can print [i/total] progress.
  echo "$envs" | nl -ba | xargs -P "$PARALLEL" -L1 bash -c 'run_one "$@"' _
  failed=$(grep -L 'RESULT: All .* tests passed\.' "$OUTDIR"/*.log 2>/dev/null | wc -l)
  echo "Done tag $tag: $total envs, $failed failed. Logs in $OUTDIR/."
  overall_failed=$((overall_failed + failed))
done

echo
echo "Done in $((SECONDS - start))s."
exit "$overall_failed"
