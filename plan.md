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

- The server runs in the container, next to the ACT framework. It is the single source of truth for the test list, verdicts, and completion.
- The client runs near the DUT. It knows its ISA string, polls for work, executes the binary on the DUT, posts raw output back. The client is dumb.
- Transport is TCP. `host.containers.internal:<port>` for the local host; any address for a remote DUT. No TLS or auth: loopback/LAN use only.

## API

- `POST /claim {isa, lease_seconds}` -> `{test_id, binary}` or `{done: true}`. Hands out the next unclaimed test for the ISA string, under a file lock. Claim carries a TTL.
- `POST /result {test_id, output}` -> `200`. Idempotent. Server parses the ACT pass/fail signature from the raw output, records the verdict, releases the claim.
- `GET /status?isa=<string>` -> counts per state (pending, claimed, pass, fail). For progress display.
- `GET /` -> a single static HTML page (vanilla JS, no framework, no build step) that polls `/status` and renders per-ISA progress. The page renders only data `/status` already returns; no additional endpoints.
- ELF-to-binary conversion (objcopy) happens server-side before handing out.

## Queue state

- One state file per ISA string next to the existing `summary.log` (JSON: test id -> state, verdict, claim expiry).
- Hand-out and release mutate the file under `flock`.
- Claim expiry: the server releases claims whose TTL expired without a result. A client that dies mid-run causes a retry, not a stall.
- Result posting wins over an expired claim: idempotent and last-write-verdict.
- Server restart loses nothing: state reloads from the state file.

## Test generation

- On first claim for an unknown ISA string, the server runs the existing `make elfs` step for a config derived from the ISA string, then serves binaries from `work/<config>/elfs/`.
- Tests already recorded in the state file are skipped; this matches the resume behavior of `test_all.sh`.

## Verdicts and reports

- Signature parsing stays in the container, reusing the existing verdict logic.
- The state file writes the same summary data as today, so `report_all.py` keeps working unchanged.

## Client

- Loop: claim -> write binary to temp file -> run on DUT (timeout = lease) -> post raw output and exit status -> repeat until `done`.
- Lease seconds is a client input, sized to the DUT (seconds for emulators, minutes for real hardware).
- One client per DUT. Multiple clients on one ISA string share the queue through the hand-out mechanism.

## Non-goals

- No TLS, auth, or WAN exposure.
- No persistent database.
- No push model: the server never initiates contact with a DUT.

## Open items

- Config-to-ISA-string derivation: where the mapping from ISA string to generated core config lives (server config file vs request parameter).
- Client distribution: script in this repo vs a binary shipped with the DUT.
- Whether `test_all.sh` adopts the pull model or stays as-is for the pure local case.
