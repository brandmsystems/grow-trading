"""Position-trading settings: which strategies are on (and their parameters) and the paper risk limits. Versioned in `position_settings`
(append-only, current = highest version, none stored = the defaults). Invalid settings are refused as a whole and change nothing; an unreadable
store falls back to the defaults for *analysis* and blocks automatic entries (fail closed). Paper only."""
from __future__ import annotations

import json

from sqlalchemy import text

from app.database import db
from app.services.position import strategies as pstr

RISK_SCHEMA = {                       # key: (type, min, max, default, label)
    "risk_pct": ("float", 0.05, 10.0, 2.0, "Risk per trade (% of virtual capital)"),
    "max_open_positions": ("int", 1, 20, 3, "Maximum open positions"),
    "max_portfolio_risk_pct": ("float", 0.1, 50.0, 6.0, "Maximum portfolio risk (sum of open maximum losses, % of capital)"),
    "max_lots": ("int", 1, 100, 20, "Maximum lots per position"),
    "hold_days": ("int", 2, 20, 5, "Planned holding period (trading days)"),
    "min_score": ("float", 0.0, 100.0, 60.0, "Minimum score for a BUY decision (STRONG needs 75)"),
}


def defaults() -> dict:
    return {"strategies": {k: {"enabled": True, "params": dict(s["params"])} for k, s in pstr.STRATEGIES.items()},
            "risk": {k: v[3] for k, v in RISK_SCHEMA.items()}, "auto_enter": False}


def validate(doc: dict | None) -> tuple[dict, list[str]]:
    """(clean settings, errors). Unknown keys and out-of-range values are errors; missing parts take the defaults."""
    clean, errors = defaults(), []
    doc = doc if isinstance(doc, dict) else {}
    for top in set(doc) - {"strategies", "risk", "auto_enter"}:
        errors.append(f"{top}: unknown setting")
    for k, g in (doc.get("strategies") or {}).items():
        if k not in pstr.STRATEGIES:
            errors.append(f"strategies.{k}: unknown strategy"); continue
        if not isinstance(g, dict):
            errors.append(f"strategies.{k}: must be an object"); continue
        if "enabled" in g:
            if isinstance(g["enabled"], bool):
                clean["strategies"][k]["enabled"] = g["enabled"]
            else:
                errors.append(f"strategies.{k}.enabled: must be true or false")
        for pk, pv in (g.get("params") or {}).items():
            base = pstr.STRATEGIES[k]["params"]
            if pk not in base:
                errors.append(f"strategies.{k}.params.{pk}: unknown parameter")
            elif isinstance(pv, bool) or not isinstance(pv, (int, float)) or not pv > 0:
                errors.append(f"strategies.{k}.params.{pk}: must be a number above zero")
            else:
                clean["strategies"][k]["params"][pk] = type(base[pk])(pv)
    for k, v in (doc.get("risk") or {}).items():
        if k not in RISK_SCHEMA:
            errors.append(f"risk.{k}: unknown setting"); continue
        typ, lo, hi, _, label = RISK_SCHEMA[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi or (typ == "int" and float(v) != int(v)):
            errors.append(f"risk.{k}: {label} must be {'a whole number ' if typ == 'int' else ''}between {lo:g} and {hi:g}")
        else:
            clean["risk"][k] = int(v) if typ == "int" else float(v)
    if "auto_enter" in doc:
        if isinstance(doc["auto_enter"], bool):
            clean["auto_enter"] = doc["auto_enter"]
        else:
            errors.append("auto_enter: must be true or false")
    return clean, errors


def current(eng=None) -> dict:
    """{version, config, error}: the saved settings, the defaults when none are saved, the defaults plus an error when the store cannot be read."""
    eng = eng or db.engine()
    try:
        with eng.connect() as c:
            r = c.execute(text("SELECT version, config, saved_at FROM position_settings ORDER BY version DESC LIMIT 1")).mappings().first()
    except Exception as exc:
        return {"version": -1, "config": defaults(), "error": f"settings could not be read ({type(exc).__name__})"}
    if not r:
        return {"version": 0, "config": defaults(), "error": None}
    clean, errors = validate(r["config"])
    return {"version": int(r["version"]), "config": defaults() if errors else clean, "error": "; ".join(errors) if errors else None}


def save(doc: dict, eng=None) -> dict:
    clean, errors = validate(doc)
    if errors:
        raise ValueError("; ".join(errors))
    eng = eng or db.engine()
    with eng.begin() as c:
        v = c.execute(text("INSERT INTO position_settings (config, note) VALUES (CAST(:c AS JSONB), 'saved') RETURNING version"), {"c": json.dumps(clean)}).scalar_one()
    return {"version": int(v), "config": clean, "error": None}


def enabled_strategies(cfg: dict) -> dict[str, dict]:
    return {k: v["params"] for k, v in cfg["strategies"].items() if v["enabled"]}
