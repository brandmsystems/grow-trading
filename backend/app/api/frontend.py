"""Serves the built React app (frontend/dist) under /app, with client-side routing fallback."""
from __future__ import annotations

from flask import Blueprint, abort, send_from_directory

from app.config import settings as config

DIST = config.BASE_DIR / "frontend" / "dist"
bp = Blueprint("frontend", __name__)


@bp.get("/app")
@bp.get("/app/")
@bp.get("/app/<path:path>")
def react_app(path: str = ""):
    if not (DIST / "index.html").exists():
        abort(404, "The React app isn't built yet: run `npm run build` in frontend/.")
    target = DIST / path
    if path and target.is_file() and DIST in target.resolve().parents:
        return send_from_directory(DIST, path)
    return send_from_directory(DIST, "index.html")   # client-side routes
