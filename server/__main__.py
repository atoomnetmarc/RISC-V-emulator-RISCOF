#!/usr/bin/env python3
# Copyright Marc Ketel
# SPDX-License-Identifier: Apache-2.0
#
# DUT work server entry point: python3 -m server [--port N]

import argparse
import logging
import sys
from http.server import ThreadingHTTPServer

from .httpd import Handler

DEFAULT_PORT = 8000

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main() -> None:
    parser = argparse.ArgumentParser(description="ACT DUT work server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    logging.info("work server listening on 0.0.0.0:%d", args.port)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
