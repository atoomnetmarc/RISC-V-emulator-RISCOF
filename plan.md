# Plan: DUT work server for ACT

The container runs the ACT framework. The DUT (native emulator, simavr/AVR, or real hardware) runs on the host or on a remote machine. The container serves work over HTTP; the DUT side pulls, runs, and reports.

## Architecture

```
+--------------------------- container ---------------------------+
|  ACT framework (ELF generation, verdict parsing, reports)      |
|  work server (Python, ThreadingHTTPServer)                     |
+----------------------^------------------^----------------------+
                       | HTTP             | HTTP
              +--------+-----+     +------+--------+
              | client (host)|     | client (host) |
              | DUT          |     | DUT           |
              +--------------+     +---------------+
```

- The server runs in the container, next to the ACT framework. It is a generic work queue: it holds no environment-selection logic. It is the single source of truth for the test list, verdicts, and completion.
- The client runs near the DUT. It claims tests for one config name, executes the binary on the DUT, posts raw output back. The client is dumb.
- Transport is TCP over a published port. `act_container.sh` publishes the server port with `-p`; a client on the local host connects to `localhost:<port>`, a remote DUT connects to the host's LAN address. No TLS or auth: loopback/LAN use only.

## API

- `POST /claim {config, lease_seconds}` -> `{test_id, binary}`, `{ready: false}`, or `{done: true}`. The config name is the existing core config identifier (`rve-rv32i`, `rve-avr-rv32im`); the server feeds it directly to `gen_core.py`. Hands out the next unclaimed test under a file lock. Claim carries a TTL.
- `POST /result {test_id, output, exit_status}` -> `200`. Idempotent. Server parses the verdict from the raw output, records it, releases the claim.
- `GET /status?config=<name>` -> counts per state (pending, claimed, generating, pass, fail). For progress display.
- `GET /` -> a single static HTML page (vanilla JS, no framework, no build step) that polls `/status` and renders per-config progress. The page renders only data `/status` already returns; no additional endpoints.
- ELF-to-binary conversion (objcopy) happens server-side before handing out.

## Queue state

- One state file per config name next to the existing `summary.log` (JSON: test id -> state, verdict, claim expiry).
- A posted result writes three artifacts inside one `flock` section: the state file entry, the `summary.log` line, and the raw output to `logs/<relpath>`. `report_all.py` reads `summary.log` and `logs/<relpath>` unchanged: the `Simulated N CPU instructions` counts and failure excerpts keep working.
- Claim expiry: the server releases claims whose TTL expired without a result. A client that dies mid-run causes a retry, not a stall.
- Result posting wins over an expired claim: idempotent and last-write-verdict.
- Server restart loses nothing: state reloads from the state file.

## Test generation

- On the first claim for an unknown config name, the server starts `make elfs` for that config in a background thread. Claims during generation return `{ready: false}`; the client sleeps briefly and polls again. The lease TTL starts only when a binary is handed out.
- Tests already recorded in the state file are skipped; a config with a complete state file serves `{done: true}`.

## Verdicts and reports

- The server parses the `RVCP-SUMMARY: TEST PASSED/FAILED` signature from the raw output with its own small parser (the framework's `run_tests.py` couples parsing to running and is not reused).
- The state file and `summary.log`/`logs/` artifacts are written together, so `report_all.py` keeps working unchanged.

## Client

- A Python 3 script in `scripts/`.
- Inputs: server URL, run command for the DUT (emulator path, firmware hex for the avr backend), `--jobs N`, lease seconds. The emulator binary is built on the DUT side with `make build` before the client starts.
- Loop per worker: claim -> write binary to temp file -> run on DUT (timeout = lease) -> post raw output and exit status -> repeat until `done`. With `--jobs N` a client runs N workers with concurrent claims.
- One client per DUT. Multiple clients on one config share the queue through the hand-out mechanism.

## Local launcher

- A thin host script (successor to the `test_all.sh` role) runs the local suite on the pull model:
  1. Select envs from the INI (`--full`/`--smoke`/filter regex), as `test_all.sh` does.
  2. Build each env's emulator binary on the host, serialized with `flock`.
  3. Start the server via `act_container.sh` with the port published.
  4. Start one client per env with `--jobs $(nproc)`.
- The launcher holds the only copy of the selection logic; the server stays generic.

## Non-goals

- No TLS, auth, or WAN exposure.
- No persistent database.
- No push model: the server never initiates contact with a DUT.
- No emulator build or distribution by the server or client: the DUT side builds its own binary.
