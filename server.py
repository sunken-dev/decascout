#!/usr/bin/env python3
"""Serve the DecaScout static dashboard and its generated daily snapshot."""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("DECASCOUT_HOST", "127.0.0.1")
PORT = int(os.environ.get("DECASCOUT_PORT", "8080"))


class DecaScoutHandler(SimpleHTTPRequestHandler):
    """Static-file handler with a tiny health endpoint for local checks."""

    server_version = "DecaScoutStatic/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            catalog_path = ROOT / "data" / "catalog.json"
            try:
                catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                payload = {
                    "ok": True,
                    "service": "decascout-static-snapshot",
                    "generated_at": catalog.get("generated_at"),
                    "products": catalog.get("product_count", len(catalog.get("products", []))),
                    "stores": catalog.get("store_count", len(catalog.get("stores", []))),
                }
            except (OSError, ValueError, TypeError) as exc:
                payload = {"ok": False, "service": "decascout-static-snapshot", "error": str(exc)}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if payload["ok"] else 503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path in {"/", "/decascout.html"}:
            self.path = "/decascout.html"
        super().do_GET()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"[decascout] {self.address_string()} - {fmt % args}\n")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), DecaScoutHandler)
    print(f"DecaScout running at http://{HOST}:{PORT}/decascout.html")
    print("The website reads data/catalog.json; refresh it with scripts/discover_catalog.py.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping DecaScout")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
