from __future__ import annotations

import argparse
import contextlib
import http.server
import os
import socketserver
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import uvicorn

from API.app.main import create_app


class _ThreadingHttpServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def _wait_for_url(url: str, *, timeout_sec: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            with urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        time.sleep(0.4)
    raise TimeoutError(f"Timed out while waiting for {url}")


def _resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_frontend_dist(repo_root: Path) -> Path:
    configured = os.environ.get("FANBAN_FRONTEND_DIST", "").strip()
    if configured:
        return Path(configured).resolve()
    return (repo_root / "frontend" / "dist").resolve()


def _start_api_server(host: str, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    app = create_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="fanban-api", daemon=True)
    thread.start()
    return server, thread


def _start_frontend_server(frontend_dist: Path, host: str, port: int) -> tuple[_ThreadingHttpServer, threading.Thread]:
    def handler(*args, **kwargs):
        return http.server.SimpleHTTPRequestHandler(
            *args,
            directory=str(frontend_dist),
            **kwargs,
        )

    server = _ThreadingHttpServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="fanban-web", daemon=True)
    thread.start()
    return server, thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto Fanban desktop validation launcher.")
    parser.add_argument("--api-port", type=int, default=18080)
    parser.add_argument("--web-port", type=int, default=18081)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    repo_root = _resolve_repo_root()
    frontend_dist = _resolve_frontend_dist(repo_root)
    if not frontend_dist.exists():
        raise FileNotFoundError(
            f"Frontend dist not found at {frontend_dist}. Run `npm run build` in frontend first."
        )

    api_server, api_thread = _start_api_server(args.host, args.api_port)
    frontend_server, frontend_thread = _start_frontend_server(frontend_dist, args.host, args.web_port)
    try:
        _wait_for_url(f"http://{args.host}:{args.api_port}/api/system/health")
        _wait_for_url(f"http://{args.host}:{args.web_port}/index.html")
        try:
            import webview
        except ImportError as exc:  # pragma: no cover - depends on desktop runtime
            raise RuntimeError(
                "pywebview is required for desktop validation. Install backend desktop extras first."
            ) from exc

        webview.create_window(
            "Auto Fanban Font Sync",
            f"http://{args.host}:{args.web_port}",
            width=1500,
            height=980,
            min_size=(1200, 760),
        )
        webview.start()
    finally:
        frontend_server.shutdown()
        frontend_server.server_close()
        frontend_thread.join(timeout=2)
        api_server.should_exit = True
        api_thread.join(timeout=2)


if __name__ == "__main__":
    main()
