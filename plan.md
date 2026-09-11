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
- `client/` — the puller that reads the ini, posts the batch, claims, runs the DUT, and posts results.
- `scripts/act_container.sh` — the container launcher. The only shell script that remains.

## API

- `POST /batch {configs: [{config, tag}], lease_seconds}` -> `{accepted: true}`. The client posts the full list of `(config, tag)` pairs it intends to run. The server starts `make elfs` for each config in a serialized background queue. The config name is the existing core config identifier (`rve-rv32i`, `rve-avr-rv32im`); the server feeds it directly to `gen_core.py`. The tag is the compiler tag (`gcc`, `clang`, `gcc-13`); the server keys queues by `(config, tag)`.
- `POST /claim {config, tag, lease_seconds}` -> `{test_id, binary}`, `{ready: false}`, or `{done: true}`. Hands out the next unclaimed test under a file lock. Claim carries a TTL. Returns `{ready: false}` while that config's ELFs are still generating; the client sleeps briefly and polls again. Returns `{done: true}` when the config's state file is complete.
- `POST /result {test_id, config, tag, output, exit_status}` -> `200`. Idempotent. Server parses the verdict from the raw output, records it, releases the claim.
- `GET /status?config=<name>&tag=<tag>` -> counts per state (pending, claimed, generating, pass, fail). For the live progress display.
- `GET /` -> a single static HTML page (vanilla JS, no framework, no build step) that polls `/status` and renders per-`(config, tag)` progress. The page renders only data `/status` returns; no additional endpoints.
- `GET /report` -> a static HTML page that renders the per-instruction, cross-config failure report (overall pass percentage, per-instruction pass/fail counts, failing envs, log excerpts, `Simulated N CPU instructions` totals). This replaces the standalone `report_all.py` script.
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
- Per-config streaming: as soon as one config's `make elfs` finishes, the client can claim and run tests for that config while later configs generate. The unit of readiness is the whole config, not individual ELFs.
- Claims for a config still generating return `{ready: false}`; the client sleeps briefly and polls again. The lease TTL starts only when a binary is handed out.
- Tests already recorded in the state file are skipped; a `(config, tag)` with a complete state file serves `{done: true}`.

## Verdicts and reports

- The server parses the `RVCP-SUMMARY: TEST PASSED/FAILED` signature from the raw output with its own small parser (the framework's `run_tests.py` couples parsing to running and is not reused).
- The server is the sole owner of verdict parsing and report rendering. The `GET /` page shows live progress; the `GET /report` page shows the final per-instruction cross-config report. Both read the same `summary.log` and `logs/` artifacts the server writes.

## Client

- A Python 3 package in `client/`, pip-installable.
- Inputs: server URL, the emulator's `platformio_isa-extension-combination_env.ini` path, selection mode (`--full`/`--smoke`/filter regex), compiler tag, run command for the DUT (emulator path, firmware hex for the avr backend), `--jobs N`, lease seconds. The emulator binary is built on the DUT side with `make build` before the client starts.
- The client reads the ini, selects the ISA strings with the same `--full`/`--smoke`/filter logic as `test_all.sh`, maps each to a config name via the `# act-config:` comment, and posts the full `(config, tag)` list to the server in one `POST /batch`.
- The client then iterates over each `(config, tag)` pair: claim -> write binary to temp file -> run on DUT (timeout = lease) -> post raw output and exit status -> repeat until `done` for that pair, then move to the next. With `--jobs N` a client runs N workers with concurrent claims within one config at a time.
- One client per DUT. Multiple clients on one `(config, tag)` share the queue through the hand-out mechanism.

## Scripts

- `scripts/act_container.sh` stays: it starts the container that auto-runs the server.
- `scripts/test_all.sh`, `scripts/run_test.sh`, `scripts/elf2bin.sh` are removed. Env selection, objcopy, and the emulator-run wrapper move into the server and client packages as inline `subprocess` calls.

## Non-goals

- No TLS, auth, or WAN exposure.
- No persistent database.
- No push model: the server never initiates contact with a DUT.
- No emulator build or distribution by the server or client: the DUT side builds its own binary.
