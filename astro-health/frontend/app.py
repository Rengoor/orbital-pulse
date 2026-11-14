"""Local HTTP server entrypoint for the Vitalis UI frontend (127.0.0.1:8080).

Owner: person C
"""

from __future__ import annotations

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(FRONTEND_DIR))
    with ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"Vitalis UI serving locally at http://{host}:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    serve()
