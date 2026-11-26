"""Background job for position trading (started with the server; disable with POSITION_SCHEDULER=0). Paper only.

* every 5 minutes on weekdays during 09:15-15:30: manage the open paper positions with live quotes (read-only; skipped when Groww is unreachable);
* once after 15:45 on a weekday: record that day's decision in the decision history, and manage the positions once more (the 15:15 time exits).
It never opens a position by itself unless `auto_enter` is on AND the idea passes every entry rule (default off)."""
from __future__ import annotations

import logging
import threading
import time as _time
from datetime import time

log = logging.getLogger("position.scheduler")
_started = False


def start(poll_sec: int = 60) -> None:
    global _started
    if _started:
        return
    _started = True

    def loop():
        last_manage = None
        decided = None
        while True:
            try:
                from app.api import position as api
                from app.services.position import account
                from app.services.position import settings as psettings
                from app.utils.timeutil import now_naive
                now = now_naive()
                if now.weekday() < 5:
                    if time(9, 15) <= now.time() < time(15, 30) and (last_manage is None or (now - last_manage).total_seconds() >= 300):
                        last_manage = now
                        ev = account.manage(now, account.live_price)
                        if any("reason" in e for e in ev):
                            log.info("position exits: %s", [e for e in ev if "reason" in e])
                    if now.time() >= time(15, 45) and decided != now.date():
                        decided = now.date()
                        a = api._analysis(force=True)
                        log.info("position decision %s: %s", a.get("day"), api.record_decision(a))
                        account.manage(now, account.live_price)
                        s = psettings.current()
                        if s["config"]["auto_enter"] and not s["error"]:
                            for o in a.get("opportunities", []):
                                try:
                                    log.info("position auto entry: %s", account.open_position(o, a["day"], s["config"]["risk"], now, auto=True))
                                except account.Refused as exc:
                                    log.info("position auto entry refused: %s", exc)
            except Exception as exc:
                log.warning("position scheduler: %s", exc)
            _time.sleep(poll_sec)

    threading.Thread(target=loop, name="position", daemon=True).start()
