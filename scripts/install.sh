#!/usr/bin/env bash
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# install.sh - build the non-system tools for the ACT integration.
#
# The script checks the system prerequisites (the pacman/yay tools listed in
# the README), then builds the Sail compiler, the RISC-V Sail model, and the
# ACT4 framework under ./work/src/ (gitignored). Re-running is safe: each step
# skips work that is already done.

set -euo pipefail

# Repo root, resolved from the script's own location so the Makefile defaults
# match regardless of the user's working directory. Does not depend on git.
RISC_TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/work"
SRC_DIR="${RISC_TOOLS}/src"

# Pinned versions, matching the README.
SAIL_TAG="0.20.2"
SAIL_MODEL_TAG="0.10"
ACT_TAG="4.0.0"
OCAML_SWITCH="5.5.0"

# Sail model binary, at the path the Makefile's SAIL_BIN points to.
SAIL_BIN="${SRC_DIR}/sail-riscv/build/c_emulator"
SAIL_SIM="${SAIL_BIN}/sail_riscv_sim"

# System prerequisites checked with `command -v`.
PREREQ_COMMANDS=(
    python
    pip
    git
    virtualenv
    make
    cmake
    opam
    z3
    uv
    curl
    riscv32-unknown-elf-gcc
    riscv32-unknown-elf-objcopy
    gcc
)

# GMP header is a system library, not a command, so check the file exists.
GMP_HEADER="/usr/include/gmp.h"

# Run a step in a subshell so a failing command prints "Step <name> failed"
# and exits 1 instead of tripping set -e silently.
run_step() {
    local name="$1"
    shift
    if ( set -e; "$@" ); then
        :
    else
        printf 'Step %s failed\n' "$name"
        exit 1
    fi
}

# Clone a repository into a directory. Skips if the directory already exists
# at the pinned tag; errors if it exists at a different tag.
clone_repo() {
    local url="$1"
    local tag="$2"
    local dir="$3"

    if [ -d "$dir" ]; then
        if [ "$(git -C "$dir" describe --tags 2>/dev/null)" = "$tag" ]; then
            printf 'Skipping clone %s (already at tag %s)\n' "$dir" "$tag"
            return 0
        fi
        printf 'Error: %s exists but is not at tag %s. Delete it and re-run.\n' \
            "$dir" "$tag"
        return 1
    fi
    git clone --branch "$tag" "$url" "$dir"
}

check_prereqs() {
    local missing=0
    local total=0
    local cmd

    printf 'Prerequisite check:\n'
    printf '| %-26s | %-8s |\n' 'tool' 'status'
    printf '|%s|%s|\n' '----------------------------' '----------'

    for cmd in "${PREREQ_COMMANDS[@]}"; do
        total=$((total + 1))
        if command -v "$cmd" >/dev/null 2>&1; then
            printf '| %-26s | %-8s |\n' "$cmd" 'OK'
        else
            printf '| %-26s | %-8s |\n' "$cmd" 'MISSING'
            missing=$((missing + 1))
        fi
    done

    total=$((total + 1))
    if [ -f "$GMP_HEADER" ]; then
        printf '| %-26s | %-8s |\n' 'gmp.h' 'OK'
    else
        printf '| %-26s | %-8s |\n' 'gmp.h' 'MISSING'
        missing=$((missing + 1))
    fi

    printf '|%s|%s|\n' '----------------------------' '----------'
    printf '%d of %d prerequisites found, %d missing.\n' \
        "$((total - missing))" "$total" "$missing"

    if [ "$missing" -gt 0 ]; then
        exit 1
    fi
}

setup_opam_switch() {
    if opam switch list --short 2>/dev/null | grep -qx "$OCAML_SWITCH"; then
        printf 'Skipping opam switch %s (already built)\n' "$OCAML_SWITCH"
        return 0
    fi
    printf 'Building opam switch %s...\n' "$OCAML_SWITCH"
    opam init -y --disable-sandboxing
    if ! opam switch create "$OCAML_SWITCH"; then
        printf 'Switch creation failed, updating opam package index and retrying...\n'
        opam update
        opam switch create "$OCAML_SWITCH"
    fi
}

build_sail_compiler() {
    if sail --version >/dev/null 2>&1; then
        printf 'Skipping Sail compiler (already built)\n'
        return 0
    fi
    printf 'Building Sail compiler...\n'
    clone_repo "https://github.com/rems-project/sail.git" "$SAIL_TAG" "${SRC_DIR}/sail"
    cd "${SRC_DIR}/sail"
    opam install . --deps-only -y
    dune build --release
    dune install
}

build_sail_model() {
    if [ -f "$SAIL_SIM" ]; then
        printf 'Skipping Sail model (already built)\n'
        return 0
    fi
    printf 'Building Sail model...\n'
    clone_repo "https://github.com/riscv/sail-riscv.git" "$SAIL_MODEL_TAG" "${SRC_DIR}/sail-riscv"
    cd "${SRC_DIR}/sail-riscv"
    DOWNLOAD_GMP=FALSE ./build_simulator.sh
    if [ ! -f "$SAIL_SIM" ]; then
        printf 'Error: %s was not produced by the build.\n' "$SAIL_SIM"
        return 1
    fi
}

clone_act() {
    clone_repo "https://github.com/riscv/riscv-arch-test.git" "$ACT_TAG" "${SRC_DIR}/riscv-arch-test"
}

install_mise_binary() {
    printf 'Installing mise...\n'
    curl https://mise.jdx.dev/install.sh | sh
}

provision_mise() {
    cd "${SRC_DIR}/riscv-arch-test"
    if mise which ruby >/dev/null 2>&1 && mise which uv >/dev/null 2>&1; then
        printf 'Skipping mise install of ruby/uv (already provisioned)\n'
    else
        printf 'Installing ruby and uv via mise...\n'
        mise install
    fi
}

# The ACT framework needs the UDB ruby gems at test-generation time. Install
# them here so the first `make elfs` does not have to.
install_udb_gems() {
    local gemfile_dir="${SRC_DIR}/riscv-arch-test/framework/src/act/data"
    if (cd "$gemfile_dir" && bundle check >/dev/null 2>&1); then
        printf 'Skipping UDB gems (bundle check passes)\n'
        return 0
    fi
    printf 'Installing UDB ruby gems...\n'
    (cd "$gemfile_dir" && bundle install)
}

# --- Check phase -----------------------------------------------------------
check_prereqs

# --- Build phase -----------------------------------------------------------

# opam switch. The eval must run in this shell so the switch stays active for
# the Sail compiler build.
run_step "opam switch setup" setup_opam_switch
eval "$(opam env --switch "$OCAML_SWITCH")"

# Sail compiler.
run_step "Sail compiler build" build_sail_compiler

# Sail model.
run_step "Sail model build" build_sail_model

# ACT4 clone.
run_step "ACT4 clone" clone_act

# mise binary. The PATH export must persist in this shell so mise stays
# callable for the provisioning step.
if ! mise --version >/dev/null 2>&1; then
    run_step "mise binary install" install_mise_binary
    export PATH="$HOME/.local/bin:$PATH"
fi

# ruby and uv provisioned by mise from the ACT4 clone's .mise.toml.
run_step "mise install of ruby/uv" provision_mise

# Shims dir so bundle/ruby are callable without a full mise activation. Set
# here, not in provision_mise, because run_step runs in a subshell.
export PATH="$HOME/.local/share/mise/shims:$PATH"

# UDB ruby gems for the ACT framework.
run_step "UDB gems install" install_udb_gems

printf '\nDone.\n'