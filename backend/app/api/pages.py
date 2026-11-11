"""Legacy server-rendered pages (removed one by one as React replaces them)."""
from __future__ import annotations

from flask import Blueprint, render_template


bp = Blueprint("pages", __name__)


@bp.get("/")
def dashboard():
    return render_template("dashboard.html")


@bp.get("/account")
def account():
    return render_template("account.html")


@bp.get("/data")
def data_page():
    return render_template("data.html")


@bp.get("/history")
def history_page():
    return render_template("history.html")


@bp.get("/compare")
def compare_page():
    return render_template("compare.html")


@bp.get("/signals")
def signals_page():
    return render_template("signals.html")
