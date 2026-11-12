"""Grow Trading backend: Flask application factory."""
from __future__ import annotations

import logging

from flask import Flask

from app.config import settings as config
from app.database import db
from app.services.market_data import history as data_manager

log = logging.getLogger("app")


def create_app() -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__, static_folder=None)   # the only interface is the React app (frontend/dist at /app)
    app.json.sort_keys = False
    try:
        db.init()
        data_manager.recover_interrupted()
    except Exception as exc:  # the account page still works without Postgres
        log.error("Database init failed: %s", exc)
    from app.api import account, backtest, data, frontend, live, pages, research
    for mod in (pages, account, backtest, data, research, live, frontend):
        app.register_blueprint(mod.bp)
    return app
