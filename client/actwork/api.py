# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# HTTP client for the work server. Transport errors are retried with
# backoff; HTTP error statuses are not.

import json
import time
import urllib.error
import urllib.request

RETRY_DELAYS = [1, 2, 4, 8, 15]

# The work server runs on the local network; never route requests through a
# proxy, even when proxy environment variables are set.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ApiError(Exception):
    """The server responded with an error status."""


def post(base_url: str, path: str, payload: dict, retries: bool = False) -> dict:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        base_url + path, data=data, headers={"Content-Type": "application/json"}
    )
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            with _OPENER.open(request) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise ApiError(f"{path}: HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError):
            if not retries or attempt == len(RETRY_DELAYS):
                raise
    raise RuntimeError("unreachable")
