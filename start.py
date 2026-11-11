"""Start Grow Trading.

    python start.py          backend on http://127.0.0.1:5000 (serves the built frontend if present)
    python start.py --dev    backend + Vite dev server for the frontend (http://127.0.0.1:5173)

The backend runs with the project's virtual environment (.venv). Logs go to data/logs/server.log.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def venv_python() -> str:
    for p in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    return sys.executable


def main() -> int:
    dev = "--dev" in sys.argv
    (ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
    log = open(ROOT / "data" / "logs" / "server.log", "a", encoding="utf-8")
    procs = [subprocess.Popen([venv_python(), "app.py"], cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT)]
    print("Backend:  http://127.0.0.1:5000  (log: data/logs/server.log)")
    if dev:
        npm = shutil.which("npm")
        if not npm or not (FRONTEND / "package.json").exists():
            print("Frontend dev server not started: npm or frontend/package.json missing.")
        else:
            procs.append(subprocess.Popen([npm, "run", "dev"], cwd=FRONTEND, shell=os.name == "nt"))
            print("Frontend: http://127.0.0.1:5173  (proxying /api and /socket.io to the backend)")
    try:
        return procs[0].wait()
    except KeyboardInterrupt:
        return 0
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
