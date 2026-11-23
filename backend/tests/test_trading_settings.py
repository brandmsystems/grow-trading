"""Trading Settings: the registry, validation, persistence, the settings-driven signals and the API.
Pure functions on synthetic candles plus a scratch database; nothing here starts an engine or touches Groww."""
import copy
import json

import numpy as np
import pandas as pd
import psycopg2
import pytest
from sqlalchemy import text

from app.config import settings as config
from app.database import db
from app.services.strategy import bias, configured, entries, strategies
from app.services.trading import trading_settings as ts
from app.services.trading.engine_config import EngineConfig
from tests.test_bias import candles

TEST_DB = "groww_trading_test_settings"


@pytest.fixture(scope="module")
def scratch_db():
    conn = psycopg2.connect(**{**config.PG, "dbname": "postgres"})
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {TEST_DB}")
    old = db._engine
    db._engine = db.engine(TEST_DB)
    db.init()
    yield
    db._engine.dispose()
    db._engine = old
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.close()


@pytest.fixture()
def fresh(scratch_db):
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE trading_settings RESTART IDENTITY"))
    ts.invalidate()
    yield
    ts.invalidate()


def doc(**over):
    d = ts.defaults()
    for path, v in over.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = v
    return d


# ---------------------------------------------------------------- the registry covers everything that exists
def test_every_existing_strategy_indicator_and_timeframe_is_controllable():
    reg = set(ts.STRATEGIES)
    assert set(strategies.STRATEGIES) <= reg and {"bias", "confluence", "scored"} <= reg                # the seven EMA strategies and the three engines
    assert {"m_" + k for k in entries.METHODS} <= reg and len(reg) == 7 + 3 + len(entries.METHODS)       # and every research entry method
    assert ts.TIMEFRAMES == (1, 5, 15, 30)
    assert set(ts.INDICATORS) == {"ema", "vwap", "rsi", "macd", "bollinger", "volume", "fvg", "adr", "atr", "rsi_divergence", "structure"}
    for key, r in ts.STRATEGIES.items():
        assert r["label"] and r["kind"] in ("crossover", "bias", "confluence", "scored", "method") and r["note"] is not None
        assert set(r["requires"]) | set(r["requires_any"]) <= set(ts.INDICATORS), key
    for key, i in ts.INDICATORS.items():
        for p in i["params"]:
            assert p["min"] <= p["default"] <= p["max"] or p["type"] in ("choice", "time"), (key, p)
    voted = {v for i in ts.INDICATORS.values() for v in i["votes"]}
    assert voted == set(bias.INDICATORS)                       # every one of the bias engine's twelve votes belongs to exactly one toggle


def test_defaults_are_valid_keep_every_existing_strategy_on_and_reproduce_todays_engine():
    clean, errors, warnings = ts.validate(ts.defaults())
    assert errors == [] and warnings == [] and clean == ts.defaults()
    on = {k for k, s in clean["strategies"].items() if s["enabled"]}
    assert on == set(strategies.STRATEGIES) | {"bias", "confluence", "scored"}                          # research methods are OFF by default
    assert clean["timeframes"]["enabled"] == {"1": False, "5": True, "15": True, "30": True}
    r = ts.resolve(clean)
    assert r.error is None and set(r.active()) == on and len(r.bias_votes()) == 12
    cfg = EngineConfig(signal_mode="bias", entry_strategy="configured", **r.engine_overrides()).validate()      # the overrides always form a valid engine configuration
    assert (cfg.timeframe, cfg.bias_confirm_tf, cfg.entry_start, cfg.cutoff, cfg.max_open_positions) == (5, 15, "09:30", "14:30", 1)
    assert cfg.ind == {f: getattr(bias.IndParams(), f) for f in bias.IndParams.__dataclass_fields__}   # default indicator parameters = the long-standing values


# ---------------------------------------------------------------- validation
def test_invalid_values_are_errors_with_the_path_and_nothing_is_repaired_silently():
    cases = [  # (where, bad value, part of the message, the path the error must name)
        ("strategies.ema_9_21.params.fast", 30, "shorter than the slow", "strategies.ema_9_21.params.fast"),
        ("strategies.ema_9_21.params.slow", 1, "between", "strategies.ema_9_21.params.slow"),
        ("indicators.macd.params.fast", 60, "between", "indicators.macd.params.fast"), ("indicators.rsi.params.period", 1, "between", "indicators.rsi.params.period"),
        ("indicators.rsi.params.period", 7.5, "whole number", "indicators.rsi.params.period"), ("indicators.bollinger.params.std", 9, "between", "indicators.bollinger.params.std"),
        ("indicators.adr.params.period", 7, "one of 5, 10, 20", "indicators.adr.params.period"), ("rules.risk_pct", 0, "between", "rules.risk_pct"),
        ("rules.max_trades_per_day", 0, "between", "rules.max_trades_per_day"), ("rules.max_open_positions", 2, "between", "rules.max_open_positions"),
        ("rules.stop_mode", "magic", "one of", "rules.stop_mode"), ("rules.start", "25:99", "", "rules.start"), ("rules.trail_pct", 150, "between", "rules.trail_pct"),
        ("rules.reentry_enabled", "yes", "true or false", "rules.reentry_enabled"), ("timeframes.entry", 1, "must be 5 or 15", "timeframes.entry"),
        ("timeframes.trend", 5, "must be 15 or 30", "timeframes.trend"), ("timeframes.exit", "never", "'entry' or 'trend'", "timeframes.exit"),
    ]
    for where, value, msg, path in cases:
        d = doc()
        node = d
        keys = where.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
        _, errors, _ = ts.validate(d)
        assert any(e["path"] == path and msg in e["message"] for e in errors), (where, value, errors)
        assert ts.resolve(d).error, where                                   # a document with an error is never used by the engine


def test_unknown_keys_strategies_indicators_and_parameters_are_refused():
    for d, path in (({"strategies": {"nope": {"enabled": True}}}, "strategies.nope"), ({"indicators": {"nope": {"enabled": True}}}, "indicators.nope"),
                    ({"strategies": {"ema_9_21": {"params": {"bogus": 1}}}}, "strategies.ema_9_21.params.bogus"), ({"surprise": 1}, "surprise"),
                    ({"rules": {"bogus": 1}}, "rules.bogus"), ({"timeframes": {"enabled": {"7": True}}}, "timeframes.enabled.7"),
                    ({"strategies": {"ema_9_21": {"enabled": "on"}}}, "strategies.ema_9_21.enabled"), ({"rules": "x"}, "rules")):
        _, errors, _ = ts.validate(d)
        assert any(e["path"] == path for e in errors), (d, errors)


def test_a_partial_document_takes_the_defaults_for_everything_it_leaves_out():
    clean, errors, _ = ts.validate({"strategies": {"ema_9_21": {"enabled": False}}, "rules": {"risk_pct": 0.5}})
    assert errors == [] and clean["strategies"]["ema_9_21"]["enabled"] is False and clean["rules"]["risk_pct"] == 0.5
    assert clean["strategies"]["ema_5_20"]["enabled"] is True and clean["indicators"]["rsi"]["params"]["period"] == 14


def test_logically_invalid_combinations_are_errors_not_warnings():
    d = doc(timeframes__enabled={"1": False, "5": False, "15": True, "30": True})
    assert any("entry timeframe (5 minutes) is disabled" in e["message"] for e in ts.validate(d)[1])
    d = doc(timeframes__enabled={"1": False, "5": False, "15": False, "30": False})
    assert any("enable at least one timeframe" in e["message"] for e in ts.validate(d)[1])
    d = doc(timeframes__trend=15, timeframes__entry=15)
    assert any("longer than the entry timeframe" in e["message"] for e in ts.validate(d)[1])
    d = doc(indicators__atr={"enabled": False, "params": {"period": 14}})
    assert any("ATR stop needs the ATR indicator" in e["message"] for e in ts.validate(d)[1])
    assert ts.validate(doc(indicators__atr={"enabled": False, "params": {"period": 14}}, rules__stop_mode="pct"))[1] == []
    d = doc(indicators__rsi={"enabled": False, "params": {"period": 14, "overbought": 75.0, "oversold": 25.0}})
    assert any("RSI divergence needs the RSI" in e["message"] for e in ts.validate(d)[1])
    bad = ts.validate(doc(indicators__rsi={"enabled": True, "params": {"period": 14, "overbought": 75.0, "oversold": 60.0}}))[1]
    assert any(e["path"] == "indicators.rsi.params.oversold" and "between 5 and 45" in e["message"] for e in bad)       # oversold can never reach 50
    assert any("start before it ends" in e["message"] for e in ts.validate(doc(rules__start="14:30", rules__end="09:30"))[1])
    assert any("smallest stop" in e["message"] for e in ts.validate(doc(strategies__scored={"enabled": True, "params": {"stop_min_pct": 60.0, "stop_max_pct": 50.0, "min_score": 80.0, "ctx_tf": 0}}))[1])


# ---------------------------------------------------------------- blockers: a disabled indicator is never treated as enabled
def test_every_strategy_is_blocked_by_each_indicator_it_requires_and_only_by_those():
    for key, reg in ts.STRATEGIES.items():
        for need in reg["requires"]:
            d = doc()
            d["indicators"][need]["enabled"] = False
            if need == "rsi":
                d["indicators"]["rsi_divergence"]["enabled"] = False
            if need == "atr":
                d["rules"]["stop_mode"] = "pct"
            d["strategies"][key]["enabled"] = True
            clean, errors, warnings = ts.validate(d)
            assert errors == [], (key, need, errors)
            r = ts.resolve(clean)
            assert any(ts.INDICATORS[need]["label"] in b for b in r.blockers(key)), (key, need)
            assert key not in r.active(), (key, need)
            assert any(w["path"] == f"strategies.{key}" for w in warnings), (key, need)               # and the page is told
        others = [i for i in ts.INDICATORS if i not in reg["requires"] and i not in reg["requires_any"]]
        d = doc()
        for i in others:
            d["indicators"][i]["enabled"] = False
        d["indicators"]["rsi_divergence"]["enabled"] = d["indicators"]["rsi_divergence"]["enabled"] and "rsi" not in others
        d["rules"]["stop_mode"] = "pct"
        d["strategies"][key]["enabled"] = True
        r = ts.resolve(ts.validate(d)[0])
        assert r.blockers(key) == [], (key, r.blockers(key))                                          # indicators it does not use never block it


def test_a_strategy_that_is_off_is_never_active_and_a_group_is_blocked_only_when_none_of_its_indicators_is_on():
    d = doc()
    for k in d["strategies"]:
        d["strategies"][k]["enabled"] = False
    r = ts.resolve(d)
    assert r.active() == [] and any("No strategy is enabled" in w["message"] for w in ts.validate(d)[2])
    d = doc()
    for i in ("ema", "vwap", "fvg", "structure"):
        d["indicators"][i]["enabled"] = False
    r = ts.resolve(ts.validate(d)[0])
    assert any("at least one of" in b for b in r.blockers("confluence"))
    assert r.blockers("bias") == []                                                                     # the bias engine still has RSI, MACD, Bollinger and volume
    for i in ("rsi", "macd", "bollinger", "volume", "rsi_divergence"):
        d["indicators"][i]["enabled"] = False
    r = ts.resolve(ts.validate(d)[0])
    assert any("at least one of" in b for b in r.blockers("bias")) and "bias" not in r.active()


def test_a_disabled_indicator_removes_its_votes_factors_and_filters_and_enabled_ones_carry_their_parameters():
    d = doc()
    d["indicators"]["rsi"]["enabled"] = d["indicators"]["rsi_divergence"]["enabled"] = False
    d["indicators"]["macd"]["enabled"] = False
    d["indicators"]["vwap"]["enabled"] = False
    d["indicators"]["adr"]["enabled"] = False
    d["indicators"]["rsi"]["params"].update(period=9, overbought=80.0, oversold=20.0)
    d["indicators"]["macd"]["params"].update(fast=8, slow=21, signal=5)
    d["indicators"]["bollinger"]["params"].update(period=30, std=2.5)
    d["indicators"]["fvg"]["params"].update(min_atr=0.3, max_age=10)
    d["indicators"]["adr"]["params"].update(period=20, max_used=80.0)
    r = ts.resolve(ts.validate(d)[0])
    o = r.engine_overrides()
    votes = o["bias_indicators"]
    assert not {"rsi", "rsi_divergence", "macd", "vwap"} & set(votes) and {"ema_9_21", "bollinger", "volume", "sr"} <= set(votes)
    assert "vwap" not in o["cf_factors"] and o["cf_adr_filter"] is False
    assert (o["cf_fvg_min_atr"], o["sc_fvg_max_age"], o["cf_adr_period"], o["sc_adr_max_used"]) == (0.3, 10, 20, 80.0)
    ip = r.ind_params()
    assert (ip.rsi_period, ip.rsi_hi, ip.rsi_lo, ip.macd_fast, ip.macd_slow, ip.macd_signal, ip.bb_period, ip.bb_std) == (9, 80.0, 20.0, 8, 21, 5, 30, 2.5)
    assert o["ind"]["rsi_period"] == 9 and EngineConfig(signal_mode="bias", entry_strategy="configured", **o).validate().ind["bb_period"] == 30


def test_rules_map_onto_the_engine_configuration():
    d = doc(rules__risk_pct=0.5, rules__max_trades_per_day=3, rules__start="10:00", rules__end="13:00", rules__target_rr=3.0, rules__trail_pct=12.0,
            rules__cooldown_bars=4, rules__daily_loss_pct=1.5, rules__stop_mode="pct", rules__stop_pct=25.0, rules__min_score=85.0)
    d["strategies"]["bias"]["params"]["min_confidence"] = 60.0
    o = ts.resolve(ts.validate(d)[0]).engine_overrides()
    assert (o["risk_pct"], o["max_trades_per_day"], o["entry_start"], o["cutoff"], o["target_rr"], o["trail_pct"], o["bias_cooldown_bars"], o["daily_risk_pct"],
            o["stop_mode"], o["stop_pct"]) == (0.5, 3, "10:00", "13:00", 3.0, 12.0, 4, 1.5, "pct", 25.0)
    assert o["bias_min_confidence"] == 85.0 and o["cf_min_score"] == 85.0 and o["sc_min_score"] == 85.0         # the global floor raises every score threshold
    assert ts.resolve(ts.validate(doc(rules__reentry_enabled=False))[0]).engine_overrides()["max_trades_per_day"] == 1


# ---------------------------------------------------------------- the settings-driven signals, every strategy x timeframe
@pytest.fixture(scope="module")
def market():
    spot = candles(days=32, drift=0.10, seed=3, futures=True, vol=6.0)
    fut = spot.copy()
    fut["close"] += 9
    fut["volume"] = 1000.0 + (fut.index % 17) * 150
    return spot, fut


def only(key, entry=5, trend=15, **extra):
    d = doc()
    for k in d["strategies"]:
        d["strategies"][k]["enabled"] = k == key
    d["timeframes"]["entry"], d["timeframes"]["trend"] = entry, trend
    d["rules"]["min_score"] = 0.0
    for path, v in extra.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = v
    return ts.resolve(ts.validate(d)[0])


def run_configured(res, market):
    spot, fut = market
    cfg = EngineConfig(signal_mode="bias", entry_strategy="configured", **res.engine_overrides()).validate()
    bf = bias.analyse(spot, fut, bias.BiasParams.from_cfg(cfg))
    return configured.evaluate(res, spot, fut, bf, cfg, bf["close_ts"].iloc[-1])


@pytest.mark.parametrize("key", list(ts.STRATEGIES))
@pytest.mark.parametrize("entry,trend", [(5, 15), (15, 30)])
def test_every_strategy_runs_alone_at_both_entry_timeframes_and_only_it_signals(market, key, entry, trend):
    res = only(key, entry, trend)
    assert res.error is None and res.active() == [key]
    out, info = run_configured(res, market)
    assert len(out) == len(bias.analyse(*[market[0], market[1]], bias.BiasParams(primary=entry, higher=trend)))
    assert set(np.unique(out["direction"])) <= {-1, 0, 1}
    states = {r["key"]: r["state"] for r in info["strategies"]}
    assert all(s == "off" for k, s in states.items() if k != key)                              # every other strategy is OFF and was not evaluated
    assert states[key] in ("signal", "no signal", "rejected") and info["active"] == [key] and info["entry_tf"] == entry and info["trend_tf"] == trend
    assert set(info["fired"]) <= {key}


def test_the_main_strategies_actually_signal_on_both_timeframes_so_the_matrix_is_not_vacuous(market):
    for key in ("ema_9_21", "ema_5_20", "ema_9_21_macd", "bias"):
        for entry, trend in ((5, 15), (15, 30)):
            out, _ = run_configured(only(key, entry, trend, timeframes__trend_filter=False), market)
            assert (out["direction"] != 0).sum() > 0, (key, entry)


def test_an_off_or_blocked_strategy_can_never_signal_even_when_its_rules_would_fire(market):
    on, _ = run_configured(only("ema_9_21", timeframes__trend_filter=False), market)
    assert (on["direction"] != 0).sum() > 0
    d = doc()
    for k in d["strategies"]:
        d["strategies"][k]["enabled"] = False
    out, info = run_configured(ts.resolve(ts.validate(d)[0]), market)
    assert (out["direction"] == 0).all() and info["fired"] == [] and all(r["state"] == "off" for r in info["strategies"])
    blocked = only("ema_9_21_vwap", indicators__vwap={"enabled": False, "params": {}})
    out, info = run_configured(blocked, market)
    assert (out["direction"] == 0).all() and blocked.active() == [] and blocked.blockers("ema_9_21_vwap")
    st_ = {r["key"]: r for r in info["strategies"]}["ema_9_21_vwap"]
    assert st_["state"] == "blocked" and "VWAP (disabled)" in st_["reason"] and st_["direction"] == 0


def test_the_trend_filter_removes_crossovers_against_the_trend_timeframe(market):
    with_f, _ = run_configured(only("ema_5_20", timeframes__trend_filter=True), market)
    without, _ = run_configured(only("ema_5_20", timeframes__trend_filter=False), market)
    assert 0 < (with_f["direction"] != 0).sum() < (without["direction"] != 0).sum()
    ef = entries.frame(*market, 5, 15)
    tr = pd.Series(ef["trend15"].to_numpy(), index=pd.DatetimeIndex(ef["close_ts"]))
    kept = with_f[with_f["direction"] != 0]
    assert (tr.reindex(pd.DatetimeIndex(kept["close_ts"])).to_numpy() * kept["direction"].to_numpy() > 0).all()      # every kept signal agrees with the trend timeframe


def test_editing_a_strategy_parameter_changes_its_signals_without_touching_source(market):
    a, _ = run_configured(only("ema_9_21", timeframes__trend_filter=False), market)
    b, _ = run_configured(only("ema_9_21", timeframes__trend_filter=False, strategies__ema_9_21__params__fast=5, strategies__ema_9_21__params__slow=34), market)
    assert (a["direction"] != 0).sum() != (b["direction"] != 0).sum() or not (a["direction"].to_numpy() == b["direction"].to_numpy()).all()
    c, _ = run_configured(only("ema_9_21", timeframes__trend_filter=False, strategies__ema_9_21__params__fast=9, strategies__ema_9_21__params__slow=21), market)
    assert (a["direction"].to_numpy() == c["direction"].to_numpy()).all()                              # the defaults are what the strategy always did


def test_several_strategies_may_be_on_same_direction_is_one_order_and_opposite_directions_conflict(market, monkeypatch):
    spot, fut = market
    res = ts.resolve(ts.validate({"strategies": {k: {"enabled": k in ("ema_9_21", "ema_5_20")} for k in ts.STRATEGIES}, "timeframes": {"trend_filter": False}})[0])
    cfg = EngineConfig(signal_mode="bias", entry_strategy="configured", **res.engine_overrides()).validate()
    bf = bias.analyse(spot, fut, bias.BiasParams.from_cfg(cfg))
    t = pd.Timestamp(bf["close_ts"].iloc[-3])
    mk = lambda v: pd.Series([v], index=pd.DatetimeIndex([t]))                                                     # noqa: E731
    monkeypatch.setattr(configured, "crossover_series", lambda spot_, fut_, key, res_: mk(1) if key == "ema_9_21" else mk(1))
    out, info = configured.evaluate(res, spot, fut, bf, cfg, bf["close_ts"].iloc[-1])
    row = out[out["close_ts"] == t].iloc[0]
    assert row["direction"] == 1 and not row["cfg_conflict"]                                                        # two strategies, one direction: ONE signal
    monkeypatch.setattr(configured, "crossover_series", lambda spot_, fut_, key, res_: mk(1) if key == "ema_9_21" else mk(-1))
    out, _ = configured.evaluate(res, spot, fut, bf, cfg, bf["close_ts"].iloc[-1])
    row = out[out["close_ts"] == t].iloc[0]
    assert row["direction"] == 0 and row["cfg_conflict"]                                                            # opposite signals: no order
    monkeypatch.setattr(configured, "crossover_series", lambda spot_, fut_, key, res_: mk(1) if key == "ema_9_21" else mk(0))
    bf2 = bf.iloc[: list(bf["close_ts"]).index(t) + 1].reset_index(drop=True)
    out, info = configured.evaluate(res, spot, fut, bf2, cfg, t)
    assert info["direction"] == 1 and info["fired"] == ["ema_9_21"] and "BUY CE" in info["strategies"][0]["reason"]
    e = configured.explain({"confidence": 50}, info, res)
    assert e["signal"] == "BUY CE" and e["strategy"] == "ema_9_21" and e["configured"]["settings_version"] == res.version


def test_the_configured_signals_are_causal_later_candles_never_change_earlier_signals(market):
    spot, fut = market
    d = doc()
    for k in d["strategies"]:
        d["strategies"][k]["enabled"] = k in ("ema_9_21", "ema_20_50", "m_orb", "m_bb_reversal", "bias", "scored")
    d["timeframes"]["trend_filter"] = True
    res = ts.resolve(ts.validate(d)[0])
    cfg = EngineConfig(signal_mode="bias", entry_strategy="configured", **res.engine_overrides()).validate()
    cut = pd.Timestamp("2026-11-10 11:20")
    p = bias.BiasParams.from_cfg(cfg)

    def run(s, f):
        bf = bias.analyse(s, f, p)
        bf = bf[bf["close_ts"] <= cut].reset_index(drop=True)
        return configured.evaluate(res, s, f, bf, cfg, cut)[0]
    a = run(spot[spot.ts < cut], fut[fut.ts < cut])
    b = run(spot, fut)
    other = spot.copy()
    other.loc[other.ts >= cut, ["open", "high", "low", "close"]] += 400
    c = run(other, fut)
    assert len(a) == len(b) > 1000 and (a["direction"] != 0).sum() > 5
    assert (a["direction"].to_numpy() == b["direction"].to_numpy()).all() and (a["direction"].to_numpy() == c["direction"].to_numpy()).all()


def test_indicator_parameters_change_the_calculations_and_the_defaults_change_nothing(market):
    spot, fut = market
    base = bias.tf_bars(spot, fut, 5)
    same = bias.tf_bars(spot, fut, 5, bias.IndParams())
    pd.testing.assert_frame_equal(base, same)
    for name, ip, cols in (("rsi", bias.IndParams(rsi_period=7), ["rsi"]), ("macd", bias.IndParams(macd_fast=8, macd_slow=17, macd_signal=5), ["macd", "macd_hist"]),
                           ("bollinger", bias.IndParams(bb_period=30, bb_std=2.5), ["bb_up", "bb_lo"]), ("atr", bias.IndParams(atr_period=7), ["atr"]),
                           ("volume", bias.IndParams(vol_sma=50), ["vol_avg20"])):
        other = bias.tf_bars(spot, fut, 5, ip)
        assert any(not np.allclose(base[c].fillna(0), other[c].fillna(0)) for c in cols), name
        assert np.allclose(base["close"], other["close"])                                              # only the named indicator moved
    a = bias.analyse(spot, fut, bias.BiasParams())
    b = bias.analyse(spot, fut, bias.BiasParams(ind=bias.IndParams(rsi_period=7, macd_fast=8, macd_slow=17)))
    assert not np.allclose(a["confidence"], b["confidence"])


# ---------------------------------------------------------------- persistence and the API
def test_nothing_saved_means_the_defaults_at_version_zero(fresh):
    r = ts.load_current()
    assert r.version == 0 and r.saved_at is None and r.doc == ts.defaults() and r.error is None and ts.current().version == 0


def test_save_creates_versions_keeps_history_survives_a_restart_and_reset_adds_a_version(fresh):
    d = doc(rules__risk_pct=0.5)
    d["strategies"]["ema_9_21"]["enabled"] = False
    r1 = ts.save(d)
    assert r1.version == 1 and r1.saved_at is not None
    d2 = copy.deepcopy(r1.doc)
    d2["indicators"]["rsi"]["params"]["period"] = 9
    r2 = ts.save(d2)
    assert r2.version == 2
    ts.invalidate()                                                                                          # a restart: nothing cached
    now = ts.load_current()
    assert now.version == 2 and now.doc["indicators"]["rsi"]["params"]["period"] == 9 and now.doc["strategies"]["ema_9_21"]["enabled"] is False
    assert ts.current().version == 2
    with db.engine().connect() as c:
        rows = c.execute(text("SELECT version, config FROM trading_settings ORDER BY version")).all()
    assert [r[0] for r in rows] == [1, 2] and rows[0][1]["indicators"]["rsi"]["params"]["period"] == 14      # the first version is still there, unchanged
    r3 = ts.reset()
    assert r3.version == 3 and r3.doc == ts.defaults() and r3.note == "reset to defaults" and ts.load_current().doc == ts.defaults()


def test_an_invalid_save_stores_nothing(fresh):
    with pytest.raises(ts.SettingsError) as e:
        ts.save(doc(rules__risk_pct=0, strategies__ema_9_21__params__fast=50))
    assert len(e.value.errors) == 2
    with db.engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM trading_settings")).scalar() == 0


def test_an_invalid_or_unreadable_stored_configuration_fails_closed(fresh, monkeypatch):
    with db.engine().begin() as c:
        c.execute(text("INSERT INTO trading_settings (config, note) VALUES (CAST(:c AS JSONB), 'tampered')"),
                  {"c": json.dumps({"rules": {"risk_pct": -5}, "strategies": {"ghost": {"enabled": True}}})})
    ts.invalidate()
    r = ts.current()
    assert r.version == 1 and r.error and "risk_pct" in r.error and r.active() == [] and r.summary()["valid"] is False
    monkeypatch.setattr(ts, "load_current", lambda eng=None: (_ for _ in ()).throw(RuntimeError("database is down")))
    ts.invalidate()
    r = ts.current()
    assert r.version == -1 and r.error and "could not be read" in r.error and r.active() == []


@pytest.fixture()
def client(fresh):
    import app.main as app_module
    return app_module.app.test_client()


def test_api_get_returns_the_configuration_summary_meta_and_no_account_data(client):
    r = client.get("/api/trading-settings")
    d = r.get_json()["data"]
    assert r.status_code == 200 and d["version"] == 0 and d["saved_at"] is None and d["config"] == ts.defaults() and d["defaults"] == ts.defaults()
    assert len(d["meta"]["strategies"]) == 32 and len(d["meta"]["indicators"]) == 11 and d["meta"]["timeframes"]["all"] == [1, 5, 15, 30]
    assert d["summary"]["valid"] and len(d["summary"]["strategies_active"]) == 10 and d["summary"]["entry_tf"] == 5
    blob = json.dumps(d).lower()
    assert not any(w in blob for w in ("balance", "funds", "margin", "order_id", "groww_balance"))             # nothing private


def test_api_save_validate_reset_conflict_and_invalid_cases(client):
    d = doc(rules__risk_pct=0.5)
    r = client.post("/api/trading-settings/validate", json={"config": d}).get_json()["data"]
    assert r["valid"] and r["errors"] == [] and r["summary"]["rules"]["risk_pct"] == 0.5
    assert client.get("/api/trading-settings").get_json()["data"]["version"] == 0                              # validating saved nothing
    bad = client.post("/api/trading-settings/validate", json={"config": doc(rules__risk_pct=0)}).get_json()["data"]
    assert not bad["valid"] and bad["errors"][0]["path"] == "rules.risk_pct" and bad["summary"] is None
    r = client.put("/api/trading-settings", json={"config": d, "base_version": 0})
    assert r.status_code == 200 and r.get_json()["data"]["version"] == 1 and r.get_json()["data"]["saved_at"]
    assert client.get("/api/trading-settings").get_json()["data"]["config"]["rules"]["risk_pct"] == 0.5
    r = client.put("/api/trading-settings", json={"config": d, "base_version": 0})                              # a stale page
    assert r.status_code == 409 and "changed elsewhere" in r.get_json()["error"]
    r = client.put("/api/trading-settings", json={"config": doc(rules__risk_pct=0, rules__max_trades_per_day=0)})
    j = r.get_json()
    assert r.status_code == 400 and not j["ok"] and len(j["errors"]) == 2 and j["errors"][0]["path"].startswith("rules.")
    assert client.get("/api/trading-settings").get_json()["data"]["version"] == 1                              # nothing stored by the invalid save
    w = client.put("/api/trading-settings", json={"config": {"strategies": {k: {"enabled": False} for k in ts.STRATEGIES}}}).get_json()
    assert w["ok"] and any("No strategy is enabled" in x["message"] for x in w["data"]["warnings"])           # allowed to save, with a warning
    r = client.post("/api/trading-settings/reset")
    assert r.status_code == 200 and r.get_json()["data"]["version"] == 3 and r.get_json()["data"]["config"] == ts.defaults()
    assert client.put("/api/trading-settings", data="not json", content_type="application/json").status_code == 400


def test_settings_api_refuses_foreign_requests(client):
    assert client.put("/api/trading-settings", json={"config": {}}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.get("/api/trading-settings", headers={"Host": "evil.example"}).status_code == 403
