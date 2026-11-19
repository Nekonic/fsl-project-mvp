#!/usr/bin/env python3

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOOPBACK = "127.0.0.1"
MARKER_HEADER = "X-Request-ID"
CONTENT_TYPE = "text/html; charset=utf-8"
UNKNOWN = 404
METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


def answers(probes) -> dict[str, tuple[int, bytes, str]]:
    found = {}
    for probe in probes:
        response = probe.get("response") or {}
        body = response.get("body")
        text = body if isinstance(body, str) else "" if body is None else json.dumps(body)
        found[str(probe["marker"])] = (int(response.get("status") or 200), text.encode("utf-8"),
                                      str(response.get("content_type") or CONTENT_TYPE))
    return found


def handler_for(known: dict[str, tuple[int, bytes, str]]):
    class Recorded(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            status, body, kind = known.get(self.headers.get(MARKER_HEADER) or "", (UNKNOWN, b"", CONTENT_TYPE))
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self.close_connection = True

        def log_message(self, shape, *args) -> None:
            return

    for method in METHODS:
        setattr(Recorded, f"do_{method}", Recorded.answer)
    return Recorded


def server(port: int, probes) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((LOOPBACK, port), handler_for(answers(probes)))


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="probe-upstream",
        description="Answers each recorded probe with its recorded response, looked up by its X-Request-ID, "
                    "on loopback, as the upstream of the scratch CRS instance.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--probes", required=True, help="a JSON list of probes, each with a marker and a response")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    given = arguments(argv)
    with open(given.probes, encoding="utf-8") as listed:
        probes = json.load(listed)
    with server(given.port, probes) as serving:
        serving.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
