# Plan: DUT work server for ACT

The container runs the ACT framework and a work server. The DUT (native emulator, simavr/AVR, or real hardware) runs on the host or on a remote machine. The container serves work over HTTP; the DUT side pulls, runs, and reports.

## Architecture

```
+--------------------------- container ---------------------------+
|  ACT framework (ELF generation, verdict parsing, reports)      |
|  work server (Python, ThreadingHTTPServer)                     |
+----------------------^------------------^----------------------+
                       | HTTP             | HTTP
              +--------+-----+     +------+--------+
              | client (host)|     | client (host)|
              | DUT          |     | DUT          |
              +--------------+     +---------------+
```

- The server runs in the container, next to the ACT framework. It is a generic work queue: it holds no environment-selection logic. It is the single source of truth for the test list, verdicts, and completion.
- The server starts automatically when the container starts. Until a client posts a batch, it does nothing but serve HTTP and the status page.
- The client runs near the DUT. It reads the emulator's `platformio_isa-extension-combination_env.ini`, selects the ISA strings to test (`--full`/`--smoke`/filter, as `test_all.sh` does), posts the full list to the server, then iterates over each ISA string: claim tests, run the binary on the DUT, post raw output back.
- The client is started by hand, one per DUT. One client drives all selected configs for one compiler tag.
- Transport is TCP over a published port. `act_container.sh` publishes the server port with `-p`; a client on the local host connects to `localhost:<port>`, a remote DUT connects to the host's LAN address. No TLS or auth: loopback/LAN use only.

## Repository layout

One repository, strict `server/` + `client/` package split. The two packages do not import each other. The client is a standalone pip-installable package (or zipapp) deployable to a DUT; the server is a separate package. Co-development stays in one repo; the deployment boundary is the package, not the repo.

- `server/` — the work server, verdict parser, report renderer, objcopy.
- `server/static/` — the OpenAPI spec and the shared stylesheet for the HTML pages. The stylesheet defines the dark theme: one palette, one font stack, no per-page overrides. The palette and font stack are adapted from the AetherOlifant project theme (`frontend/src/assets/main.css` there): a VS-Dark palette with `#1e1e1e` background, `#252526` surface, `#2d2d30` elevated, `#3e3e42` hover and border, `#cccccc` text, `#858585` muted text, `#007acc` accent, `#4ec9b0` success, `#f44747` error. The palette is flattened into one plain CSS file with the same CSS custom properties; the pages are vanilla HTML, so Tailwind itself is not used.
- `client/` — the puller that reads the ini, posts the batch, claims, runs the DUT, and posts results.
- `scripts/act_container.sh` — the container launcher. The only shell script that remains.

## API

- `POST /batch {settings, configs: [{config, tag}], lease_seconds}` -> `{accepted: true}`. The client posts the full list of `(config, tag)` pairs it intends to run. `settings` carries the architecture-specific generation parameters (load base, halt address, and every other template parameter) that the server substitutes into the generation templates. `lease_seconds` is optional with a default of 30 seconds. The server starts `make elfs` for each config in a serialized background queue. The config is the normalized ISA string (`rv32i`, `rv32imacb_zicsr_zifencei`); the tag is a free-form label (`gcc`, `clang`, `gcc-13`, `avr`, `simavr`) that namespaces both results and the generated binaries. The server keys queues by `(config, tag)`.
- `POST /batch` is an idempotent merge: a `(config, tag)` pair the server already knows is ignored, unknown pairs are appended to the queue. A client restart can re-post its batch without losing results. Settings are last-write-wins per tag: a post with settings that differ from the stored ones invalidates and regenerates all binaries for that tag. Running two clients with different settings under one tag is a usage error; the artifacts follow the last post.
- `POST /claim {config, tag, lease_seconds}` -> `{test_id, binary}`, `{ready: false}`, or `{done: true}`. Hands out the next unclaimed test under a file lock. Claim carries a TTL. Returns `{ready: false}` while that config's ELFs are still generating; the client sleeps briefly and polls again. Returns `{done: true}` when the config's state file is complete. If generation for the config failed, `/claim` responds with an error status; the client stops polling that pair and reports the failure.
- `POST /result {test_id, config, tag, output, exit_status}` -> `200`. Idempotent. Server parses the verdict from the raw output, records it, releases the claim.
- `GET /status?config=<name>&tag=<tag>` -> counts per state (pending, claimed, generating, pass, fail). For the live progress display.
- `GET /` -> a single static HTML page (vanilla JS, no framework, no build step) that polls `/status` and renders per-`(config, tag)` progress. The page renders only data `/status` returns; no additional endpoints. The `/` and `/report` pages share one stylesheet and one dark theme.
- `GET /report` -> a static HTML page that renders the per-instruction, cross-config failure report (overall pass percentage, per-instruction pass/fail counts, failing envs, log excerpts, `Simulated N CPU instructions` totals). This replaces the standalone `report_all.py` script.
- `GET /openapi.yaml` -> the hand-written OpenAPI spec. The spec is the source of truth for the API surface; client and server both follow it.
- ELF-to-binary conversion (objcopy) happens server-side before handing out, as one `subprocess` call to `riscv64-unknown-elf-objcopy` (the toolchain lives in the container).

## Queue state

- One state file per `(config, tag)` pair next to the existing `summary.log` (JSON: test id -> state, verdict, claim expiry).
- The state file records per-test states only. Generation status is in-memory and is not persisted: a server restart mid-generation re-runs `make elfs`, which is incremental and therefore cheap.
- A posted result writes three artifacts inside one `flock` section: the state file entry, the `summary.log` line, and the raw output to `logs/<relpath>`.
- Claim expiry: the server releases claims whose TTL expired without a result. A client that dies mid-run causes a retry, not a stall.
- Result posting wins over an expired claim: idempotent and last-write-verdict.
- Server restart loses no results: the state file and `summary.log`/`logs/` reload.

## Test generation

- On the initial `POST /batch`, the server queues `make elfs` for each config in a serialized background queue: one config generates at a time. The client builds its emulator binary (`make build`) concurrently on the DUT side.
- The server holds no knowledge of targets, the ini, or ISA strings. The client reads the emulator's ini on the DUT side, normalizes the selected ISA strings, and posts them as the config values. The server treats a config name as an opaque string.
- `gen_core.py` accepts the bare ISA string as the config name, a `--tag` argument, and a `--settings` JSON file argument. The `rve-`/`rve-avr-` name prefixes and the name-based backend inference are removed. The settings schema is fixed: `{"load_base": <addr>, "halt_address": <addr>}`, no defaults; an incomplete post is a 400. `gen_core.py` validates the settings and substitutes them into the parameterized templates (`link.ld`, `rvmodel_macros.h`), so one generated config serves any DUT that matches the settings. The server shells out to `gen_core.py` per `(config, tag)` with the posted settings; it holds no template knowledge of its own.
- Every on-disk path is two-level per pair: generated configs in `config/cores/atoomnetmarc/<CONFIG>/<TAG>/` and ELFs, state, and summaries under the ACT work dir `work/<CONFIG>/<TAG>/`. The Makefile gains a `TAG` variable threaded through all these paths. Tags cannot collide and settings invalidation is per-pair.
- Per-config streaming: as soon as one config's `make elfs` finishes, the client can claim and run tests for that config while later configs generate. The unit of readiness is the whole config, not individual ELFs.
- Claims for a config still generating return `{ready: false}`; the client sleeps briefly and polls again. The lease TTL starts only when a binary is handed out.
- When `make elfs` for a config finishes, the server enumerates the test ids for that config by listing the built ELF directory: each ELF file name is a test id. No framework support is needed; the server owns discovery and the client never needs to know the test list.
- Tests already recorded in the state file are skipped; a `(config, tag)` pair with a complete state file serves `{done: true}`.

## Verdicts and reports

- The server parses the `RVCP-SUMMARY: TEST PASSED/FAILED` signature from the raw output with its own small parser (the framework's `run_tests.py` couples parsing to running and is not reused).
- Raw output without the signature (crash, timeout, truncated output) is a definitive FAIL with the exit status recorded. There is no retry: the server re-queues nothing.
- The lease TTL doubles as the run timeout: the client kills the DUT process when the lease expires and posts the truncated output, which fails the test for lack of a signature.
- Generation failure (a failing `make elfs`) is an error status from `/claim` and `/status`; the client stops polling that pair. A client-side transport error or timeout on any endpoint is retried with backoff; an error status from the server is not.
- The server is the sole owner of verdict parsing and report rendering. The `GET /` page shows live progress; the `GET /report` page shows the final per-instruction cross-config report. Both read the same `summary.log` and `logs/` artifacts the server writes.

## Config selection

- Every DUT project's ini marks its env blocks with `# isa: <bare ISA string>` and optionally `# smoke`. The client parses the ini in pure Python: it reads `[env:...]` blocks, selects all marked envs for `--full` or the `# smoke`-marked ones for `--smoke`, and applies the filter regex to the ISA string. The config value is the marked bare ISA string; the env name travels to the server as the optional `firmware_env` setting so generation targets the right firmware environment. No shell dependencies; `test_all.sh` is deleted.

## Client

- A Python 3 package in `client/`, pip-installable.
- Inputs: server URL, the DUT project's PlatformIO ini path (the native emulator's `platformio_isa-extension-combination_env.ini` or the AVR project's `platformio.ini`), selection mode (`--full`/`--smoke`/filter regex), compiler tag, the generation settings for its DUT (load base, halt address), `--run` command template for the DUT, `--jobs N`, lease seconds. The emulator binary is built on the DUT side with `make build` before the client starts.
- The DUT run command is a single `--run` template with a `{binary}` placeholder, for example `--run './emu {binary}'` or `--run 'simavr -m atmega328p --firmware {binary}'`. The client substitutes the claimed binary path and executes the template with the shell. The client holds no backend knowledge: any DUT that fits a shell command works.
- The client reads the ini, selects the ISA strings with the same `--full`/`--smoke`/filter logic as `test_all.sh`, normalizes each string, and posts its generation settings plus the full `(config, tag)` list to the server in one `POST /batch`.
- The client then iterates over each `(config, tag)` pair: claim -> write binary to temp file -> run on DUT (timeout = lease) -> post raw output and exit status -> repeat until `done` for that pair, then move to the next. With `--jobs N` a client runs N workers with concurrent claims within one config at a time.
- One client per DUT. Multiple clients on one `(config, tag)` pair share the queue through the hand-out mechanism.

## Scripts

- `scripts/act_container.sh` stays: it starts the container that auto-runs the server.
- `scripts/test_all.sh`, `scripts/run_test.sh`, `scripts/elf2bin.sh` are removed. Env selection, objcopy, and the emulator-run wrapper move into the server and client packages as inline `subprocess` calls.

## Non-goals

- No TLS, auth, or WAN exposure.
- No persistent database.
- No push model: the server never initiates contact with a DUT.
- No emulator build or distribution by the server or client: the DUT side builds its own binary.
