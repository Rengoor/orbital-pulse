"""Start the whole demo with one command: backend, crew simulator, and all three views.

    backend/.venv/bin/python run_demo.py          # macOS / Linux
    backend\\.venv\\Scripts\\python run_demo.py    # Windows

What it does:
  1. Starts the backend (API + UI) on http://127.0.0.1:8000.
  2. Starts the daily-vitals simulator (simulated crew C001-C004, labelled simulated).
  3. Opens the helmet HUD, the crew health monitor and the Earth base in the browser.
Ctrl+C stops everything.

Options: --port N, --no-sim (backend and pages only), --storm (simulator storm
mode), --no-browser, --interval S (simulator seconds between rounds).
SIGNING_KEY is taken from the environment; without it a local development key
is used and the backend says so in its log.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VIEWS = {
    # The HUD starts its own "Steady work" scenario (simulated, labelled so) for its wearer.
    "Helmet HUD": "/ui/hud/index.html?scenario=nominal",
    "Crew health monitor": "/ui/tablet/monitor.html",
    "Earth base": "/ui/earth/index.html",
}


def wait_for(url: str, proc: subprocess.Popen, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"The backend exited during startup (code {proc.returncode}). See the log above.")
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.3)
    raise SystemExit(f"The backend did not answer {url} within {timeout:.0f} s.")


def port_in_use(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
        return True
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-sim", action="store_true", help="do not start the crew simulator")
    ap.add_argument("--storm", action="store_true", help="simulator storm mode (dose rate climbs)")
    ap.add_argument("--interval", type=float, default=10.0, help="simulator seconds between rounds")
    ap.add_argument("--no-browser", action="store_true", help="do not open the pages")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)   # show progress even when piped to a file

    base = f"http://127.0.0.1:{args.port}"
    if port_in_use(args.port):
        print(f"Something is already answering on {base}. Stop it first, or pass --port.")
        return 1

    env = dict(os.environ)
    if not env.get("SIGNING_KEY"):
        env["SIGNING_KEY"] = "local-dev-signing-key"
        print("SIGNING_KEY not set; using the local development key (records are for this demo only).")

    procs: list[subprocess.Popen] = []

    def stop_all(*_: object) -> None:
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    try:
        print(f"Starting the backend on {base} ...")
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.api.main:create_app", "--factory",
             "--host", "127.0.0.1", "--port", str(args.port), "--log-level", "warning"],
            cwd=ROOT, env=env))
        wait_for(base + "/health", procs[0])

        if not args.no_sim:
            sim = [sys.executable, "-m", "data.sim.simulator", "--url", base, "--interval", str(args.interval)]
            if args.storm:
                sim.append("--storm")
            print("Starting the crew simulator (C001-C004, simulated data) ...")
            procs.append(subprocess.Popen(sim, cwd=ROOT, env=env, stdout=subprocess.DEVNULL))

        print()
        for name, path in VIEWS.items():
            print(f"  {name:22s} {base}{path}")
            if not args.no_browser:
                webbrowser.open_new_tab(base + path)
        print("\nThe HUD asks for camera access: allow it to see the camera view and use hand gestures.")
        print("Press Ctrl+C to stop everything.")

        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
        while True:
            for p in procs:
                if p.poll() is not None:
                    print(f"A process exited (code {p.returncode}); stopping the demo.")
                    return 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping ...")
        return 0
    finally:
        stop_all()


if __name__ == "__main__":
    sys.exit(main())
