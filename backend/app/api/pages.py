"""Old page addresses. The app has one interface, the React app at /app; these routes
send the root URL and old bookmarks to the matching React page."""
from __future__ import annotations

from flask import Blueprint, redirect

bp = Blueprint("pages", __name__)

# Old address -> React route (under /app).
REDIRECTS = {
    "/": "/app/",
    "/live": "/app/live",
    "/signals": "/app/signals",
    "/compare": "/app/compare",
    "/data": "/app/data",
    "/history": "/app/history",
    "/account": "/app/account",
    "/backtest": "/app/backtest",
}


def _make(target: str):
    def view():
        return redirect(target, code=302)
    return view


for _path, _target in REDIRECTS.items():
    bp.add_url_rule(_path, endpoint=f"to_{_target.strip('/').replace('/', '_') or 'app'}", view_func=_make(_target))
