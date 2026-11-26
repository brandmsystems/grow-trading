"""Trading Settings: one centrally managed, persisted configuration for the paper-trading engine.

What it holds: which strategies may generate signals (each with its own parameters), which timeframes are enabled and which one
is used for the trend, the entry and the exit confirmation, which indicators participate (with their parameters), and the paper
trading rules (score floor, trade limits, stop, target, risk, trailing, trading window, re-entry, daily loss).

How it is used (no duplicate engine, no UI-only toggles):
* `Engine._settings_gate` (every entry of every mode goes through `Engine._try_entry`) refuses an order unless its strategy is ON, none
  of the indicators it requires is OFF and its timeframe is enabled, and refuses everything while the saved configuration is invalid.
* The entry strategy `configured` (bias mode, paper and replay only) takes its signals from the strategies that are ON
  (`strategy/configured.py`), and re-reads this configuration on every tick: a change applies to the next candle, with no restart.
* Every order records the version, the strategies that fired, the timeframes and the enabled indicators (`analysis.settings`).

Storage: table `trading_settings` (migration 0021), append-only, current = highest version; no rows = the defaults (version 0).
Everything here is pure except `load_current` / `save` (database). Paper and replay only: nothing here can place an order.
"""
from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from app.database import db
from app.services.strategy import bias, confluence, entries, strategies
from app.utils.timeutil import parse_hm

TIMEFRAMES = (1, 5, 15, 30)
ENTRY_TFS = (5, 15)                 # the engine decides on closed 5- or 15-minute candles
TREND_TFS = (15, 30)                # the trend timeframe confirms the entry candle: longer than it, and a multiple of it
EXIT_ROLES = ("entry", "trend")     # exit confirmation: the entry candle's opposite signal, or the trend timeframe turning against the trade
TIMEFRAME_NOTES = {1: "Cannot be used for entry, trend or exit confirmation in this engine (it decides on closed 5- or 15-minute candles); stored for reference.",
                   5: "Entry candle.", 15: "Entry candle or trend confirmation.", 30: "Trend confirmation."}


def _p(key, label, typ, lo, hi, default, choices=None):
    return {"key": key, "label": label, "type": typ, "min": lo, "max": hi, "default": default, **({"choices": choices} if choices else {})}


# ---------------------------------------------------------------- indicators (key -> label, parameters, which votes it owns in the bias engine)
INDICATORS: dict[str, dict] = {
    "ema": {"label": "EMA", "params": [], "note": "Periods are set per strategy (fast / slow of each crossover). The bias, confluence and scored strategies use a fixed 20/50/200 trend set.",
            "votes": ["ema_9_21", "ema_5_20", "ema_8_21", "ema_20_50", "ema_200"]},
    "vwap": {"label": "VWAP", "params": [], "note": "Session VWAP of the near-month NIFTY future (the index has no volume).", "votes": ["vwap"]},
    "rsi": {"label": "RSI", "params": [_p("period", "Period", "int", 2, 50, 14), _p("overbought", "Overbought", "float", 55, 95, 75.0), _p("oversold", "Oversold", "float", 5, 45, 25.0)],
            "note": "Overbought / oversold limit where the scored strategy still counts RSI as momentum.", "votes": ["rsi"]},
    "macd": {"label": "MACD", "params": [_p("fast", "Fast", "int", 2, 50, 12), _p("slow", "Slow", "int", 3, 100, 26), _p("signal", "Signal", "int", 2, 50, 9)], "note": "", "votes": ["macd"]},
    "bollinger": {"label": "Bollinger Bands", "params": [_p("period", "Period", "int", 5, 100, 20), _p("std", "Standard deviations", "float", 0.5, 4.0, 2.0)], "note": "", "votes": ["bollinger"]},
    "volume": {"label": "Volume / Volume SMA", "params": [_p("sma_period", "SMA period", "int", 5, 100, 20)], "note": "Futures volume against its average.", "votes": ["volume"]},
    "fvg": {"label": "Fair value gap (FVG)", "params": [_p("min_atr", "Smallest gap (× ATR)", "float", 0.0, 5.0, 0.1), _p("max_age", "Gap tradable for (candles)", "int", 1, 200, 24)], "note": "", "votes": []},
    "adr": {"label": "Average daily range (ADR)", "params": [_p("period", "Sessions", "choice", 5, 20, 10, [5, 10, 20]), _p("max_used", "No entry once used (%)", "float", 10.0, 1000.0, 100.0)], "note": "", "votes": []},
    "atr": {"label": "ATR", "params": [_p("period", "Period", "int", 2, 50, 14)], "note": "Used by the ATR stop, the volatility filter and several strategies.", "votes": []},
    "rsi_divergence": {"label": "RSI divergence", "params": [_p("pivot", "Pivot confirmed after (bars)", "int", 1, 10, 3), _p("decay", "Valid for (bars)", "int", 1, 30, 6)], "note": "Needs RSI.", "votes": ["rsi_divergence"]},
    "structure": {"label": "Market structure / Support & resistance", "params": [_p("swing", "Swing pivot confirmed after (bars)", "int", 1, 10, 3)],
                  "note": "Swing highs and lows, previous-day high and low.", "votes": ["sr"]},
}
_RSI_DEP = {"rsi_divergence": ["rsi"]}          # an indicator that cannot work without another

# ---------------------------------------------------------------- strategies
_CONFIRM = {None: [], "vwap": ["vwap"], "rsi": ["rsi"], "macd": ["macd"]}
_METHOD_REQUIRES = {
    "cross_9_21": ["ema"], "cross_5_20": ["ema"], "cross_8_21": ["ema"], "cross_9_21_vwap": ["ema", "vwap"], "continuation_9_21": ["ema", "atr"],
    "pullback_9_21": ["ema", "atr"], "stack_20_50_200": ["ema"], "rsi_divergence": ["rsi", "rsi_divergence"], "macd_cross": ["macd"], "macd_hist_trend": ["macd"],
    "bb_breakout": ["bollinger", "volume"], "bb_reversal": ["bollinger"], "vwap_breakout": ["vwap"], "vwap_retest": ["vwap", "atr"], "sr_breakout": ["structure"],
    "sr_retest": ["structure", "atr"], "sr_rejection": ["structure", "atr"], "volume_momentum": ["volume", "atr"], "atr_breakout": ["atr"], "orb": ["atr"],
    "consolidation_breakout": ["atr"], "trend_reversal": ["ema"],
}


def _strategy_registry() -> dict[str, dict]:
    reg: dict[str, dict] = {}
    for key, s in strategies.STRATEGIES.items():
        reg[key] = {"label": s.label, "kind": "crossover", "requires": ["ema"] + _CONFIRM[s.confirm], "requires_any": [],
                    "params": [_p("fast", "Fast EMA", "int", 2, 200, s.fast), _p("slow", "Slow EMA", "int", 3, 400, s.slow)],
                    "note": f"EMA {s.fast}/{s.slow} crossover" + (f", confirmed by {s.confirm.upper()}" if s.confirm else "") + "."}
    reg["bias"] = {"label": "Bias votes (12 indicators)", "kind": "bias", "requires": [], "requires_any": [i for i, d in INDICATORS.items() if d["votes"]],
                   "params": [_p("min_confidence", "Minimum confidence (%)", "float", 0, 100, 70.0), _p("trend_thr", "Trend needs ± score", "float", 0.0, 1.0, 0.25),
                              _p("confirm_thr", "Entry candle needs ± score", "float", 0.0, 1.0, 0.20)],
                   "note": "Weighted vote of every enabled indicator; the votes of a disabled indicator are removed."}
    reg["confluence"] = {"label": "Confluence (FVG + VWAP + ADR + EMA + structure)", "kind": "confluence", "requires": [], "requires_any": ["ema", "vwap", "fvg", "structure"],
                         "params": [_p("min_score", "Confirmation score needed (%)", "float", 0, 100, 75.0), _p("htf", "Trend timeframe must not be against", "bool", 0, 1, True)],
                         "note": "Each of EMA, VWAP, FVG and structure is a factor only while its indicator is ON; ADR filters only while ADR is ON."}
    reg["scored"] = {"label": "Scored (structure + EMA + VWAP + FVG + ADR)", "kind": "scored", "requires": ["ema", "vwap", "rsi", "macd", "volume", "fvg", "adr", "atr", "structure"], "requires_any": [],
                     "params": [_p("min_score", "Minimum score (of 100)", "float", 0, 100, 80.0), _p("ctx_tf", "Context timeframe (0 = off)", "choice", 0, 60, 0, [0, 30, 60]),
                                _p("stop_min_pct", "Stop at least (% of premium)", "float", 0, 100, 5.0), _p("stop_max_pct", "Stop at most (% of premium)", "float", 1, 100, 50.0)],
                     "note": "Every component earns points, so it needs every indicator it scores: with one OFF it cannot trade."}
    for key, label in entries.METHODS.items():
        reg["m_" + key] = {"label": label, "kind": "method", "requires": _METHOD_REQUIRES[key], "requires_any": [], "params": [],
                           "note": "Research entry method (fixed rules). The five-year research found no profitable method; OFF by default."}
    return reg


STRATEGIES = _strategy_registry()
DEFAULT_ON = tuple(strategies.STRATEGIES) + ("bias", "confluence", "scored")      # every strategy the product already had is ON; research methods are OFF

BULK_SCOPES = ("strategies", "indicators", "timeframes")


def defaults() -> dict:
    """The default configuration: reproduces what the engine does today, with every existing strategy and indicator ON."""
    return {
        "strategies": {k: {"enabled": k in DEFAULT_ON, "params": {p["key"]: p["default"] for p in v["params"]}} for k, v in STRATEGIES.items()},
        "timeframes": {"enabled": {"1": False, "5": True, "15": True, "30": True}, "entry": 5, "trend": 15, "exit": "entry", "trend_filter": True},
        "indicators": {k: {"enabled": True, "params": {p["key"]: p["default"] for p in v["params"]}} for k, v in INDICATORS.items()},
        "rules": {"min_score": 0.0, "max_trades_per_day": 6, "max_open_positions": 1, "max_open_risk_pct": 3.0, "max_strategy_positions": 1,
                  "max_strategy_risk_pct": 1.5, "scan_min_quality": 55.0, "scan_allow_unvalidated": False, "stop_mode": "atr", "stop_atr": 1.0, "stop_pct": 30.0, "stop_points": 20.0,
                  "target_rr": 2.0, "profit_target_net": 0.0, "risk_pct": 1.0, "trail_pct": 0.0, "trail_activate_pct": 10.0, "start": "09:30", "end": "14:30",
                  "reentry_enabled": True, "cooldown_bars": 2, "daily_loss_pct": 0.0, "daily_loss_rupees": 0.0},
    }


RULE_SCHEMA = [
    _p("min_score", "Minimum confidence / signal score (floor, 0 = each strategy's own)", "float", 0, 100, 0.0),
    _p("max_trades_per_day", "Maximum trades a day (0 = no count cap: the risk limits still apply)", "int", 0, 1000, 6),
    _p("max_open_positions", "Maximum concurrent positions (several only for the scanner)", "int", 1, 20, 1),
    _p("max_open_risk_pct", "Maximum total open risk (% of virtual capital, 0 = off)", "float", 0.0, 100.0, 3.0),
    _p("max_strategy_positions", "Maximum concurrent positions per strategy", "int", 1, 20, 1),
    _p("max_strategy_risk_pct", "Maximum open risk per strategy (% of virtual capital, 0 = off)", "float", 0.0, 100.0, 1.5),
    _p("scan_min_quality", "Scanner: minimum quality score (of 100)", "float", 0.0, 100.0, 55.0),
    _p("scan_allow_unvalidated", "Scanner: also trade strategies without a validated positive result (research use)", "bool", 0, 1, False),
    _p("stop_mode", "Stop-loss method", "choice", 0, 0, "atr", ["atr", "pct", "points"]), _p("stop_atr", "Stop: delta × ATR multiple", "float", 0.1, 10.0, 1.0),
    _p("stop_pct", "Stop: % of premium", "float", 1.0, 99.0, 30.0), _p("stop_points", "Stop: premium points", "float", 0.5, 10000.0, 20.0),
    _p("target_rr", "Target (× the stop distance)", "float", 0.1, 20.0, 2.0), _p("profit_target_net", "Net profit target per trade (₹, 0 = off)", "float", 0.0, 1e7, 0.0),
    _p("risk_pct", "Risk per trade (% of virtual capital)", "float", 0.05, 100.0, 1.0), _p("trail_pct", "Trailing stop (% from the best premium, 0 = off)", "float", 0.0, 99.0, 0.0),
    _p("trail_activate_pct", "Trail starts after (% in profit)", "float", 0.0, 1000.0, 10.0), _p("start", "Trading starts", "time", 0, 0, "09:30"), _p("end", "Trading ends", "time", 0, 0, "14:30"),
    _p("reentry_enabled", "Allow re-entry after an exit (off = one trade a day)", "bool", 0, 1, True), _p("cooldown_bars", "Cool-down after an exit (candles)", "int", 0, 20, 2),
    _p("daily_loss_pct", "Daily loss limit (% of the day's starting capital, 0 = off)", "float", 0.0, 100.0, 0.0), _p("daily_loss_rupees", "Daily loss limit (₹, 0 = off)", "float", 0.0, 1e9, 0.0),
]


def meta() -> dict:
    """What the page needs to draw every control: labels, parameter schemas, requirements, timeframe roles."""
    return {
        "strategies": [{"key": k, "label": v["label"], "kind": v["kind"], "requires": v["requires"], "requires_any": v["requires_any"], "params": v["params"], "note": v["note"]}
                       for k, v in STRATEGIES.items()],
        "indicators": [{"key": k, "label": v["label"], "params": v["params"], "note": v["note"], "depends_on": _RSI_DEP.get(k, [])} for k, v in INDICATORS.items()],
        "timeframes": {"all": list(TIMEFRAMES), "entry": list(ENTRY_TFS), "trend": list(TREND_TFS), "exit": list(EXIT_ROLES), "notes": {str(k): v for k, v in TIMEFRAME_NOTES.items()}},
        "rules": RULE_SCHEMA,
    }


# ---------------------------------------------------------------- validation
class SettingsError(ValueError):
    """The configuration is invalid; `errors` is a list of {path, message}."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("; ".join(f"{e['path']}: {e['message']}" for e in errors))


def _coerce(p: dict, v, path: str, errors: list):
    t = p["type"]
    try:
        if t == "bool":
            if not isinstance(v, bool):
                raise ValueError("must be true or false")
            return v
        if t == "time":
            parse_hm(str(v))
            return str(v)
        if t == "choice":
            v = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
            ch = p.get("choices") or []
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            if v not in ch:
                raise ValueError(f"must be one of {', '.join(map(str, ch))}")
            return v
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("must be a number")
        if t == "int":
            if float(v) != int(v):
                raise ValueError("must be a whole number")
            v = int(v)
        else:
            v = float(v)
        if not p["min"] <= v <= p["max"]:
            raise ValueError(f"must be between {p['min']:g} and {p['max']:g}")
        return v
    except ValueError as exc:
        errors.append({"path": path, "message": str(exc) if str(exc) and "could not convert" not in str(exc) else "is not a valid value"})
        return p["default"]


def validate(doc: dict | None) -> tuple[dict, list[dict], list[dict]]:
    """(clean configuration, errors, warnings). Missing parts take the defaults; unknown keys and invalid values are errors and the
    configuration must not be saved while there are any. Warnings (a strategy that cannot trade because a required indicator is
    OFF, no strategy ON, ...) do not block saving: the engine simply does not trade those strategies."""
    clean, errors, warnings = defaults(), [], []
    doc = doc if isinstance(doc, dict) else {}
    for top in doc:
        if top not in clean:
            errors.append({"path": top, "message": "unknown setting"})

    # strategies
    given = doc.get("strategies", {})
    if not isinstance(given, dict):
        errors.append({"path": "strategies", "message": "must be an object"})
        given = {}
    for key, g in given.items():
        if key not in STRATEGIES:
            errors.append({"path": f"strategies.{key}", "message": "unknown strategy"})
            continue
        if not isinstance(g, dict):
            errors.append({"path": f"strategies.{key}", "message": "must be an object"})
            continue
        if "enabled" in g:
            if isinstance(g["enabled"], bool):
                clean["strategies"][key]["enabled"] = g["enabled"]
            else:
                errors.append({"path": f"strategies.{key}.enabled", "message": "must be true or false"})
        schema = {p["key"]: p for p in STRATEGIES[key]["params"]}
        for pk, pv in (g.get("params") or {}).items():
            if pk not in schema:
                errors.append({"path": f"strategies.{key}.params.{pk}", "message": "unknown parameter"})
            else:
                clean["strategies"][key]["params"][pk] = _coerce(schema[pk], pv, f"strategies.{key}.params.{pk}", errors)
        for k_ in set(g) - {"enabled", "params"}:
            errors.append({"path": f"strategies.{key}.{k_}", "message": "unknown setting"})

    # indicators
    given = doc.get("indicators", {})
    if not isinstance(given, dict):
        errors.append({"path": "indicators", "message": "must be an object"})
        given = {}
    for key, g in given.items():
        if key not in INDICATORS:
            errors.append({"path": f"indicators.{key}", "message": "unknown indicator"})
            continue
        if not isinstance(g, dict):
            errors.append({"path": f"indicators.{key}", "message": "must be an object"})
            continue
        if "enabled" in g:
            if isinstance(g["enabled"], bool):
                clean["indicators"][key]["enabled"] = g["enabled"]
            else:
                errors.append({"path": f"indicators.{key}.enabled", "message": "must be true or false"})
        schema = {p["key"]: p for p in INDICATORS[key]["params"]}
        for pk, pv in (g.get("params") or {}).items():
            if pk not in schema:
                errors.append({"path": f"indicators.{key}.params.{pk}", "message": "unknown parameter"})
            else:
                clean["indicators"][key]["params"][pk] = _coerce(schema[pk], pv, f"indicators.{key}.params.{pk}", errors)
        for k_ in set(g) - {"enabled", "params"}:
            errors.append({"path": f"indicators.{key}.{k_}", "message": "unknown setting"})

    # timeframes
    tf = doc.get("timeframes", {})
    if not isinstance(tf, dict):
        errors.append({"path": "timeframes", "message": "must be an object"})
        tf = {}
    for k_ in set(tf) - {"enabled", "entry", "trend", "exit", "trend_filter"}:
        errors.append({"path": f"timeframes.{k_}", "message": "unknown setting"})
    for k, v in (tf.get("enabled") or {}).items():
        if k not in clean["timeframes"]["enabled"]:
            errors.append({"path": f"timeframes.enabled.{k}", "message": "unknown timeframe (use 1, 5, 15 or 30)"})
        elif isinstance(v, bool):
            clean["timeframes"]["enabled"][k] = v
        else:
            errors.append({"path": f"timeframes.enabled.{k}", "message": "must be true or false"})
    for role, allowed in (("entry", ENTRY_TFS), ("trend", TREND_TFS)):
        if role in tf:
            if tf[role] in allowed and not isinstance(tf[role], bool):
                clean["timeframes"][role] = int(tf[role])
            else:
                errors.append({"path": f"timeframes.{role}", "message": f"must be {' or '.join(map(str, allowed))} minutes"
                               + (" (the engine decides on closed 5- or 15-minute candles)" if role == "entry" else "")})
    if "exit" in tf:
        if tf["exit"] in EXIT_ROLES:
            clean["timeframes"]["exit"] = tf["exit"]
        else:
            errors.append({"path": "timeframes.exit", "message": "must be 'entry' or 'trend'"})
    if "trend_filter" in tf:
        if isinstance(tf["trend_filter"], bool):
            clean["timeframes"]["trend_filter"] = tf["trend_filter"]
        else:
            errors.append({"path": "timeframes.trend_filter", "message": "must be true or false"})

    # rules
    given = doc.get("rules", {})
    if not isinstance(given, dict):
        errors.append({"path": "rules", "message": "must be an object"})
        given = {}
    schema = {p["key"]: p for p in RULE_SCHEMA}
    for k, v in given.items():
        if k not in schema:
            errors.append({"path": f"rules.{k}", "message": "unknown setting"})
        else:
            clean["rules"][k] = _coerce(schema[k], v, f"rules.{k}", errors)

    _cross_checks(clean, errors)
    if not errors:
        warnings = _warnings(clean)
    return clean, errors, warnings


def _cross_checks(c: dict, errors: list):
    for key, s in c["strategies"].items():
        if STRATEGIES[key]["kind"] == "crossover" and s["params"]["fast"] >= s["params"]["slow"]:
            errors.append({"path": f"strategies.{key}.params.fast", "message": "the fast EMA must be shorter than the slow EMA"})
        if key == "scored" and s["params"]["stop_min_pct"] >= s["params"]["stop_max_pct"]:
            errors.append({"path": "strategies.scored.params.stop_min_pct", "message": "the smallest stop % must be below the largest"})
    m = c["indicators"]["macd"]["params"]
    if m["fast"] >= m["slow"]:
        errors.append({"path": "indicators.macd.params.fast", "message": "the MACD fast period must be shorter than the slow period"})
    tf = c["timeframes"]
    en = {int(k): v for k, v in tf["enabled"].items()}
    if not any(en.values()):
        errors.append({"path": "timeframes.enabled", "message": "enable at least one timeframe"})
    for role in ("entry", "trend"):
        if not en.get(tf[role], False):
            errors.append({"path": f"timeframes.{role}", "message": f"the {role} timeframe ({tf[role]} minutes) is disabled: enable it or choose another"})
    if tf["trend"] <= tf["entry"] or tf["trend"] % tf["entry"]:
        errors.append({"path": "timeframes.trend", "message": "the trend timeframe must be longer than the entry timeframe and a multiple of it"})
    rl = c["rules"]
    if rl["stop_mode"] == "atr" and not c["indicators"]["atr"]["enabled"]:
        errors.append({"path": "rules.stop_mode", "message": "the ATR stop needs the ATR indicator enabled (or choose a percentage or points stop)"})
    if parse_hm(rl["start"]) >= parse_hm(rl["end"]):
        errors.append({"path": "rules.start", "message": "trading must start before it ends"})
    if c["indicators"]["rsi_divergence"]["enabled"] and not c["indicators"]["rsi"]["enabled"]:
        errors.append({"path": "indicators.rsi_divergence.enabled", "message": "RSI divergence needs the RSI indicator enabled"})


def blockers(c: dict, key: str) -> list[str]:
    """Why a strategy cannot trade under configuration `c` (empty = it can). A disabled indicator is never treated as enabled."""
    reg, out = STRATEGIES[key], []
    ind = c["indicators"]
    for i in reg["requires"]:
        if not ind[i]["enabled"]:
            out.append(f"needs {INDICATORS[i]['label']} (disabled)")
    if reg["requires_any"] and not any(ind[i]["enabled"] for i in reg["requires_any"]):
        out.append("needs at least one of: " + ", ".join(INDICATORS[i]["label"] for i in reg["requires_any"]) + " (all disabled)")
    tf = c["timeframes"]
    en = {int(k): v for k, v in tf["enabled"].items()}
    if not en.get(tf["entry"], False):
        out.append(f"the entry timeframe ({tf['entry']} minutes) is disabled")
    return out


def _warnings(c: dict) -> list[dict]:
    out = []
    on = [k for k, s in c["strategies"].items() if s["enabled"]]
    if not on:
        out.append({"path": "strategies", "message": "No strategy is enabled: the engine will place no orders."})
    for k in on:
        b = blockers(c, k)
        if b:
            out.append({"path": f"strategies.{k}", "message": f"{STRATEGIES[k]['label']} is ON but cannot trade: " + "; ".join(b) + "."})
    if on and not any(not blockers(c, k) for k in on):
        out.append({"path": "strategies", "message": "Every enabled strategy is blocked: the engine will place no orders."})
    if c["timeframes"]["enabled"].get("1"):
        out.append({"path": "timeframes.enabled.1", "message": TIMEFRAME_NOTES[1]})
    return out


# ---------------------------------------------------------------- the resolved view the engine reads
@dataclass
class Resolved:
    version: int
    saved_at: datetime | None
    doc: dict
    error: str | None = None            # set when the stored configuration is invalid: the engine then refuses every entry
    note: str | None = None

    # strategies
    def strategy_enabled(self, key: str) -> bool:
        return bool(self.doc["strategies"].get(key, {}).get("enabled"))

    def blockers(self, key: str) -> list[str]:
        return blockers(self.doc, key) if key in STRATEGIES else ["unknown strategy"]

    def active(self) -> list[str]:
        """Strategies that may generate signals now: ON and not blocked."""
        if self.error:
            return []
        return [k for k in STRATEGIES if self.strategy_enabled(k) and not self.blockers(k)]

    def params(self, key: str) -> dict:
        return self.doc["strategies"][key]["params"]

    # indicators
    def indicator_enabled(self, key: str) -> bool:
        return bool(self.doc["indicators"][key]["enabled"])

    def enabled_indicators(self) -> list[str]:
        return [k for k in INDICATORS if self.indicator_enabled(k)]

    def ind_params(self) -> bias.IndParams:
        i = self.doc["indicators"]
        return bias.IndParams(rsi_period=i["rsi"]["params"]["period"], rsi_hi=i["rsi"]["params"]["overbought"], rsi_lo=i["rsi"]["params"]["oversold"],
                              macd_fast=i["macd"]["params"]["fast"], macd_slow=i["macd"]["params"]["slow"], macd_signal=i["macd"]["params"]["signal"],
                              bb_period=i["bollinger"]["params"]["period"], bb_std=i["bollinger"]["params"]["std"], atr_period=i["atr"]["params"]["period"],
                              vol_sma=i["volume"]["params"]["sma_period"], div_k=i["rsi_divergence"]["params"]["pivot"], div_decay=i["rsi_divergence"]["params"]["decay"],
                              swing_k=i["structure"]["params"]["swing"])

    def bias_votes(self) -> list[str]:
        """The bias engine's vote keys that belong to an enabled indicator."""
        return [v for k, d in INDICATORS.items() if self.indicator_enabled(k) for v in d["votes"]]

    # timeframes
    @property
    def entry_tf(self) -> int:
        return self.doc["timeframes"]["entry"]

    @property
    def trend_tf(self) -> int:
        return self.doc["timeframes"]["trend"]

    @property
    def exit_role(self) -> str:
        return self.doc["timeframes"]["exit"]

    @property
    def trend_filter(self) -> bool:
        return bool(self.doc["timeframes"]["trend_filter"])

    def timeframe_enabled(self, tf: int) -> bool:
        return bool(self.doc["timeframes"]["enabled"].get(str(int(tf))))

    def engine_overrides(self) -> dict:
        """EngineConfig fields the `configured` entry strategy takes from this configuration on every tick."""
        d, rl, ind = self.doc, self.doc["rules"], self.doc["indicators"]
        fvg, adr = ind["fvg"]["params"], ind["adr"]["params"]
        factors = [f for f, i in (("ema", "ema"), ("vwap", "vwap"), ("fvg", "fvg"), ("structure", "structure")) if ind[i]["enabled"]]
        b, cf, sc = d["strategies"]["bias"]["params"], d["strategies"]["confluence"]["params"], d["strategies"]["scored"]["params"]
        return {
            "timeframe": self.entry_tf, "bias_confirm_tf": self.trend_tf, "entry_start": rl["start"], "cutoff": rl["end"],
            "max_trades_per_day": 1 if not rl["reentry_enabled"] else rl["max_trades_per_day"], "max_open_positions": rl["max_open_positions"],
            "max_open_risk_pct": rl["max_open_risk_pct"], "max_strategy_positions": rl["max_strategy_positions"], "max_strategy_risk_pct": rl["max_strategy_risk_pct"],
            "scan_min_quality": rl["scan_min_quality"], "scan_allow_unvalidated": rl["scan_allow_unvalidated"],
            "risk_pct": rl["risk_pct"], "stop_mode": rl["stop_mode"], "stop_atr": rl["stop_atr"], "stop_pct": rl["stop_pct"], "stop_points": rl["stop_points"],
            "target_rr": rl["target_rr"], "profit_target_net": rl["profit_target_net"], "trail_pct": rl["trail_pct"], "trail_activate_pct": rl["trail_activate_pct"],
            "bias_cooldown_bars": rl["cooldown_bars"], "daily_risk_pct": rl["daily_loss_pct"], "max_daily_loss": rl["daily_loss_rupees"],
            "bias_indicators": self.bias_votes() or list(bias.INDICATORS), "bias_min_confidence": max(b["min_confidence"], rl["min_score"]),
            "bias_trend_thr": b["trend_thr"], "bias_confirm_thr": b["confirm_thr"],
            "cf_factors": factors or list(confluence.FACTORS), "cf_min_score": max(cf["min_score"], rl["min_score"]), "cf_htf": cf["htf"], "cf_adr_filter": bool(ind["adr"]["enabled"]),
            "cf_adr_period": adr["period"], "cf_adr_max_used": adr["max_used"], "cf_fvg_min_atr": fvg["min_atr"], "cf_fvg_max_age": fvg["max_age"],
            "sc_min_score": max(sc["min_score"], rl["min_score"]), "sc_ctx_tf": sc["ctx_tf"], "sc_stop_min_pct": sc["stop_min_pct"], "sc_stop_max_pct": sc["stop_max_pct"],
            "sc_adr_period": adr["period"], "sc_adr_max_used": adr["max_used"], "sc_fvg_min_atr": fvg["min_atr"], "sc_fvg_max_age": fvg["max_age"],
            "ind": {f: getattr(self.ind_params(), f) for f in self.ind_params().__dataclass_fields__},
        }

    def snapshot(self, fired: list[str]) -> dict:
        """What every order records about the configuration it was placed under."""
        return {"version": self.version, "saved_at": self.saved_at.isoformat() if self.saved_at else None, "strategies": fired,
                "timeframes": {"entry": self.entry_tf, "trend": self.trend_tf, "exit": self.exit_role,
                               "enabled": [int(k) for k, v in self.doc["timeframes"]["enabled"].items() if v]},
                "indicators": self.enabled_indicators()}

    def summary(self) -> dict:
        """The active configuration in a few lines, for the page and the engine status."""
        act, on = self.active(), [k for k in STRATEGIES if self.strategy_enabled(k)]
        rl = self.doc["rules"]
        return {"version": self.version, "saved_at": self.saved_at.isoformat() if self.saved_at else None, "valid": self.error is None, "error": self.error,
                "strategies_on": on, "strategies_active": act, "strategies_blocked": {k: self.blockers(k) for k in on if self.blockers(k)},
                "timeframes_enabled": [int(k) for k, v in self.doc["timeframes"]["enabled"].items() if v],
                "entry_tf": self.entry_tf, "trend_tf": self.trend_tf, "exit": self.exit_role, "indicators_on": self.enabled_indicators(),
                "indicators_off": [k for k in INDICATORS if not self.indicator_enabled(k)],
                "rules": {"window": f"{rl['start']}-{rl['end']}", "max_trades_per_day": rl["max_trades_per_day"], "risk_pct": rl["risk_pct"],
                          "stop": rl["stop_mode"], "target_rr": rl["target_rr"], "daily_loss_pct": rl["daily_loss_pct"], "reentry": rl["reentry_enabled"]}}


def resolve(doc: dict | None, version: int = 0, saved_at: datetime | None = None, note: str | None = None) -> Resolved:
    clean, errors, _ = validate(doc)
    if errors:
        return Resolved(version, saved_at, defaults(), "; ".join(f"{e['path']}: {e['message']}" for e in errors), note)
    return Resolved(version, saved_at, clean, None, note)


# ---------------------------------------------------------------- persistence
_cache: dict = {"key": None, "at": 0.0, "res": None}
_lock = threading.Lock()


def load_current(eng=None) -> Resolved:
    """The saved configuration (highest version); the defaults when nothing was saved. An invalid stored document yields a Resolved with
    `error` set (fail closed), never a silently repaired one."""
    eng = eng or db.engine()
    with eng.connect() as c:
        r = c.execute(text("SELECT version, config, saved_at, note FROM trading_settings ORDER BY version DESC LIMIT 1")).mappings().first()
    if not r:
        return Resolved(0, None, defaults(), None, "defaults (nothing saved yet)")
    return resolve(r["config"], int(r["version"]), r["saved_at"], r["note"])


def current(max_age: float = 1.0) -> Resolved:
    """`load_current` with a one-second cache, so the engine can call it on every tick and still see a save within a second."""
    eng = db.engine()
    key = id(eng)
    with _lock:
        if _cache["key"] == key and _time.monotonic() - _cache["at"] < max_age and _cache["res"] is not None:
            return _cache["res"]
    try:
        res = load_current(eng)
    except Exception as exc:                  # the table is missing or the database is down: nothing may trade on a guess
        res = Resolved(-1, None, defaults(), f"the saved configuration could not be read ({type(exc).__name__})")
    with _lock:
        _cache.update(key=key, at=_time.monotonic(), res=res)
    return res


def invalidate() -> None:
    with _lock:
        _cache.update(key=None, at=0.0, res=None)


def save(doc: dict, note: str = "saved", eng=None) -> Resolved:
    """Validate, then store as a new version. Raises SettingsError (nothing stored) when invalid."""
    clean, errors, _ = validate(doc)
    if errors:
        raise SettingsError(errors)
    eng = eng or db.engine()
    import json
    with eng.begin() as c:
        row = c.execute(text("INSERT INTO trading_settings (config, note) VALUES (CAST(:c AS JSONB), :n) RETURNING version, saved_at"),
                        {"c": json.dumps(clean), "n": note}).mappings().first()
    invalidate()
    return Resolved(int(row["version"]), row["saved_at"], clean, None, note)


def reset(eng=None) -> Resolved:
    """Store the defaults as a new version (the earlier versions stay in the table)."""
    return save(defaults(), "reset to defaults", eng)
