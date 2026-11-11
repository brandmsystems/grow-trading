"""Minimal background-job runner (one worker) with progress reporting."""
from __future__ import annotations

import itertools
import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("jobs")
_pools = {"main": ThreadPoolExecutor(max_workers=1, thread_name_prefix="job"),
          # Long research runs get their own lane so they don't block downloads and backtests.
          "research": ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")}
_jobs: dict[str, dict] = {}
_ids = itertools.count(1)
_lock = threading.Lock()


def submit(kind: str, fn, *args, lane: str = "main", **kwargs) -> str:
    jid = f"{kind}-{next(_ids)}"
    job = {"id": jid, "kind": kind, "state": "queued", "progress": 0.0, "message": "Queued",
           "result": None, "error": None}
    with _lock:
        _jobs[jid] = job

    def progress(frac: float, msg: str):
        job.update(progress=round(min(max(frac, 0.0), 1.0), 3), message=msg)

    def runner():
        job["state"] = "running"
        try:
            job["result"] = fn(*args, progress=progress, **kwargs)
            job.update(state="done", progress=1.0, message="Done")
        except Exception as exc:
            log.error("job %s failed: %s\n%s", jid, exc, traceback.format_exc())
            job.update(state="error", error=str(exc) or type(exc).__name__)

    _pools[lane].submit(runner)
    return jid


def get(jid: str) -> dict | None:
    return _jobs.get(jid)


def active() -> list[dict]:
    return [j for j in _jobs.values() if j["state"] in ("queued", "running")]
