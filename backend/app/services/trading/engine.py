"""Live / paper trading engine for the 9/21 EMA crossover.

The engine re-derives today's trade sequence from CLOSED bars with exactly the
same code the backtester uses (strategy.generate_legs) and acts on events it has
not processed yet. Live and backtest logic therefore cannot drift apart.

Prediction mode (signal_mode="prediction"): crosses of the chosen strategy are scored
with the Signals-page model (same features, signals.features). Only crosses scoring at
least min_score open a trade. Exits are the signal's NIFTY stop (1 x ATR) or target
(2 x ATR), judged on completed 1-minute candles exactly like the Signals outcome, or the
15:00 square-off. Opposite crosses don't exit in this mode.

Event handling per evaluation (after each signal bar closes + a grace period):
  * exit events (opposite cross) are applied before entry events at the same time;
  * entries are skipped if stale (> STALE_ENTRY_SEC after the signal bar closed),
    if the daily trade limit is reached, or if the engine is halted;
  * the 15:00 square-off is clock driven;
  * a daily loss limit (realised + open MTM) squares off and halts for the day.
"""
from __future__ import annotations

import json
import logging
import threading
import traceback
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import text

from app.services.trading import charges as costs
from app.database import db
from app.services.strategy import signals
from app.services.strategy import strategies
from app.services.strategy import rules as st
from app.services.market_data.live import Contract, OrderError, OrderUnknown

log = logging.getLogger("live.engine")

MARKET_OPEN, MARKET_CLOSE = time(9, 15), time(15, 30)


@dataclass
class EngineConfig:
    trade_mode: str = "paper"          # paper | live | replay (stored real candles, simulated clock)
    exec_mode: str = "ATM_BUY"         # ITM5_BUY | ATM_BUY | ATM_SELL
    timeframe: int = 15
    entry_start: str = "09:30"
    cutoff: str = "14:30"
    lots: int = 1
    roll_on_expiry_day: bool = True
    max_daily_loss: float = 5000.0     # ₹, realised + MTM; 0 disables
    max_trades_per_day: int = 6
    bar_grace_sec: int = 5             # wait after bar close before evaluating
    max_candle_wait_sec: int = 60      # wait for the bar's last 1m candle to appear
    stale_entry_sec: int = 180         # don't enter if the signal is older than this
    signal_mode: str = "cross"         # cross: every crossover | prediction: scored signals only
    strategy: str = "ema_9_21"         # prediction mode: whose crosses are scored
    min_score: float = 50.0            # prediction mode: minimum score to open a trade
    costs: dict = field(default_factory=lambda: costs.DEFAULT_COSTS.to_dict())

    def validate(self) -> "EngineConfig":
        if self.trade_mode not in ("paper", "live", "replay"):
            raise ValueError("trade_mode must be paper, live or replay")
        if self.exec_mode not in st.MODES:
            raise ValueError("unknown execution mode")
        if int(self.timeframe) not in (5, 15, 30):
            raise ValueError("timeframe must be 5, 15 or 30")
        self.timeframe = int(self.timeframe)
        _hm(self.entry_start), _hm(self.cutoff)
        if _hm(self.entry_start) >= _hm(self.cutoff):
            raise ValueError("entry start must be before cutoff")
        self.lots = int(self.lots)
        if self.lots < 1:
            raise ValueError("lots must be >= 1")
        self.max_daily_loss = float(self.max_daily_loss)
        self.max_trades_per_day = int(self.max_trades_per_day)
        if self.signal_mode not in ("cross", "prediction"):
            raise ValueError("signal_mode must be cross or prediction")
        if self.strategy not in strategies.STRATEGIES:
            raise ValueError("unknown strategy")
        self.min_score = float(self.min_score)
        if not 0 <= self.min_score <= 100:
            raise ValueError("minimum score must be between 0 and 100")
        self.costs = {**costs.DEFAULT_COSTS.to_dict(), **{k: float(v) for k, v in (self.costs or {}).items()}}
        return self


def _hm(s: str) -> time:
    h, m = str(s).split(":")
    return time(int(h), int(m))


class Engine:
    def __init__(self, cfg: EngineConfig, market, broker, eng=None):
        self.cfg = cfg.validate()
        self.market, self.broker = market, broker
        self.dbe = eng or db.engine()
        self.cost_cfg = costs.CostConfig(**self.cfg.costs)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.session_id: int | None = None
        self.state = "stopped"             # stopped | waiting | running | halted | error
        self.halt_reason: str | None = None
        self.day: date | None = None
        self.processed_until: datetime | None = None
        self.position: dict | None = None
        self.trades_today = 0
        self.realised_today = 0.0
        self.last_eval: dict | None = None
        self.last_ltp: dict = {}
        self.events: deque = deque(maxlen=300)
        self.exit_failures = 0
        self.bars_today: list[dict] = []
        self.last_fill_today: datetime | None = None
        self.scorer: signals.Scorer | None = None
        self._regime: tuple[date, object] | None = None
        self._ref_minute: datetime | None = None
        self.last_spot: dict | None = None        # {"ts", "price"} latest NIFTY quote
        self.conn_error: str | None = None

    # ------------------------------------------------------------ logging / persistence
    def log(self, msg: str, level: str = "info"):
        ts = self.market.now()
        self.events.appendleft({"ts": ts.isoformat(), "level": level, "message": msg})
        getattr(log, "warning" if level == "warn" else level if level in ("info", "error") else "info")(msg)
        try:
            with self.dbe.begin() as c:
                c.execute(text("INSERT INTO live_events (session_id, ts, level, message) VALUES (:s,:t,:l,:m)"),
                          {"s": self.session_id, "t": ts, "l": level, "m": msg})
        except Exception:
            pass

    def _alert(self, action: str, signal_ts, **data) -> None:
        """Record a notification. The key makes each signal alert at most once."""
        key = f"{self.cfg.trade_mode}|{self.day}|{action}|{pd.Timestamp(signal_ts).isoformat()}"
        if self.cfg.trade_mode == "replay":
            key += f"|s{self.session_id}"
        try:
            with self.dbe.begin() as c:
                c.execute(text("INSERT INTO live_alerts (alert_key, session_id, trade_mode, day, ts, action, payload) "
                               "VALUES (:k,:s,:m,:d,:t,:a,CAST(:p AS JSONB)) ON CONFLICT (alert_key) DO NOTHING"),
                          {"k": key, "s": self.session_id, "m": self.cfg.trade_mode, "d": self.day, "t": self.market.now(),
                           "a": action, "p": json.dumps({"signal_ts": pd.Timestamp(signal_ts).isoformat(), **data}, default=str)})
        except Exception as exc:
            log.warning("alert not stored: %s", exc)

    def _hold(self, leg, why: str, **extra) -> None:
        self._alert("HOLD", leg.entry_ts, direction="Bullish" if leg.direction > 0 else "Bearish",
                    nifty=round(leg.signal_close, 2), reason=why, **extra)

    def _insert_trade(self, row: dict) -> int:
        cols = ", ".join(row)
        vals = ", ".join(f":{k}" for k in row)
        with self.dbe.begin() as c:
            return c.execute(text(f"INSERT INTO live_trades ({cols}) VALUES ({vals}) RETURNING id"), row).scalar_one()

    def _update_trade(self, tid: int, row: dict):
        sets = ", ".join(f"{k}=:{k}" for k in row)
        with self.dbe.begin() as c:
            c.execute(text(f"UPDATE live_trades SET {sets} WHERE id=:id"), {**row, "id": tid})

    def _load_day_state(self, day: date):
        """Resume after a restart: open position + today's stats for this trade mode."""
        # A replay is self-contained: earlier replays of the same day must not affect it.
        own = " AND session_id=:s" if self.cfg.trade_mode == "replay" else ""
        with self.dbe.connect() as c:
            rows = c.execute(text(f"SELECT * FROM live_trades WHERE trade_mode=:m AND day=:d{own} ORDER BY id"),
                             {"m": self.cfg.trade_mode, "d": day, "s": self.session_id}).mappings().all()
        self.trades_today = len(rows)
        self.realised_today = sum(r["net"] or 0 for r in rows if r["status"] == "CLOSED")
        fills = [t for r in rows for t in (r["entry_ts"], r["exit_ts"]) if t is not None]
        self.last_fill_today = max(fills) if fills else None
        open_rows = [r for r in rows if r["status"] == "OPEN"]
        self.position = None
        if open_rows:
            r = open_rows[-1]
            self.position = {
                "id": r["id"], "direction": 1 if r["direction"] == "Bullish" else -1, "side": r["side"],
                "contract": Contract(r["trading_symbol"], r["groww_symbol"], r["expiry"], r["strike"],
                                     r["opt_type"], r["qty"]),
                "qty": r["qty"], "entry_price": r["entry_price"], "entry_ts": r["entry_ts"],
                "signal_ts": r["signal_ts"], "entry_ref": r["signal_close"], "score": r.get("score"),
                "stop_ref": r.get("stop_ref"), "target_ref": r.get("target_ref"), "atr_ref": r.get("atr_ref"),
            }
            self.log(f"Resumed open {r['side']} position {r['trading_symbol']} x{r['qty']} from earlier", "warn")
        # stale OPEN trades from previous days can't be managed (MIS is auto squared off by the broker)
        with self.dbe.begin() as c:
            n = c.execute(text("UPDATE live_trades SET status='CLOSED', exit_reason='stale_previous_day' "
                               f"WHERE trade_mode=:m AND day<:d AND status='OPEN'{own}"),
                          {"m": self.cfg.trade_mode, "d": day, "s": self.session_id}).rowcount
        if n:
            self.log(f"{n} open trade(s) from a previous day marked closed: verify them in Groww", "warn")

    # ------------------------------------------------------------ lifecycle
    def start(self, threaded: bool = True):
        if self.cfg.signal_mode == "prediction":
            label = strategies.STRATEGIES[self.cfg.strategy].label
            analysis = signals.latest(self.cfg.strategy, self.cfg.timeframe, self.cfg.entry_start, self.cfg.cutoff)
            if not analysis:
                raise ValueError(f"No Signals analysis for {label} at {self.cfg.timeframe}m. "
                                 f"Build it on the Signals page first.")
            self.scorer = signals.Scorer(analysis)
        with self.dbe.begin() as c:
            self.session_id = c.execute(text(
                "INSERT INTO live_sessions (trade_mode, config) VALUES (:m, CAST(:c AS JSONB)) RETURNING id"),
                {"m": self.cfg.trade_mode, "c": json.dumps(asdict(self.cfg))}).scalar_one()
        self.state = "waiting"
        self._stop.clear()
        self.log(f"Engine started in {self.cfg.trade_mode.upper()} mode · {st.MODE_LABELS[self.cfg.exec_mode]} · "
                 f"{self.cfg.timeframe}m · window {self.cfg.entry_start}–{self.cfg.cutoff} · {self.cfg.lots} lot(s)")
        if self.scorer:
            self.log(f"Prediction mode: {strategies.STRATEGIES[self.cfg.strategy].label} crosses scoring ≥ {self.cfg.min_score:g} only; "
                     f"exits at stop (1×ATR), target (2×ATR) or 15:00. Model built {self.scorer.built}.")
        if threaded:
            self._thread = threading.Thread(target=self._run, name="live-engine", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                self.log(f"Engine error: {exc}", "error")
                log.error(traceback.format_exc())
            self._stop.wait(1.0)

    def stop(self, square_off: bool = True, reason: str = "stopped by user"):
        with self._lock:
            if square_off and self.position:
                self._exit("manual_stop")
            self._stop.set()
            self.state = "stopped"
            self.log(f"Engine stopped ({reason})")
            try:
                with self.dbe.begin() as c:
                    c.execute(text("UPDATE live_sessions SET stopped_at=now(), stop_reason=:r WHERE id=:i"),
                              {"r": reason, "i": self.session_id})
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=40)

    def square_off_now(self):
        with self._lock:
            if self.position:
                self._exit("manual_square_off")
            else:
                self.log("Square-off requested: no open position")

    # ------------------------------------------------------------ main loop step
    def tick(self):
        with self._lock:
            now = self.market.now()
            if self.day != now.date():
                self._new_day(now)
            if now.weekday() >= 5 or now.time() < MARKET_OPEN or now.time() >= MARKET_CLOSE:
                if self.state not in ("halted", "error"):
                    self.state = "waiting"
                return
            if self.state == "waiting":
                self.state = "running"
            if not self.last_spot or (now - self.last_spot["ts"]).total_seconds() >= 5:
                try:
                    self.last_spot = {"ts": now, "price": float(self.market.spot_ltp())}
                    self.conn_error = None
                except Exception as exc:
                    self.conn_error = str(exc) or type(exc).__name__

            if self.position and now.time() >= st.SQUARE_OFF:
                self._exit("square_off")
            if self.position and self.position.get("stop_ref") is not None:
                self._check_refs(now)
            if self.position and self.exit_failures:
                self._exit(self.position.get("pending_reason", "retry"))   # retry a failed exit
            self._risk_check(now)

            nxt = self._next_bar_close(self.processed_until)
            if nxt is not None and now >= nxt + timedelta(seconds=self.cfg.bar_grace_sec):
                self._evaluate(now, nxt)

    def _new_day(self, now: datetime):
        self.day = now.date()
        self.halt_reason = None if self.state == "halted" else self.halt_reason
        if self.state == "halted":
            self.state = "waiting"
        self.exit_failures = 0
        self.last_eval = None
        self.bars_today = []
        self._load_day_state(self.day)
        # Re-check bars that closed within the stale window (entries older than that are
        # skipped anyway), but never re-process anything at/before a fill already recorded today.
        start_from = self._last_bar_close_at_or_before(now - timedelta(seconds=self.cfg.stale_entry_sec))
        if self.last_fill_today and self.last_fill_today > start_from:
            start_from = self.last_fill_today
        self.processed_until = start_from

    def _bar_closes(self, day: date) -> list[datetime]:
        tf = self.cfg.timeframe
        out, t = [], datetime.combine(day, MARKET_OPEN)
        end = datetime.combine(day, MARKET_CLOSE)
        while t < end:
            out.append(min(t + timedelta(minutes=tf), end))
            t += timedelta(minutes=tf)
        return out

    def _last_bar_close_at_or_before(self, now: datetime) -> datetime:
        closes = [c for c in self._bar_closes(now.date()) if c <= now]
        return closes[-1] if closes else datetime.combine(now.date(), MARKET_OPEN)

    def _next_bar_close(self, after: datetime | None) -> datetime | None:
        day = self.day
        for c in self._bar_closes(day):
            if after is None or c > after:
                return c if c.time() <= st.SQUARE_OFF else None   # nothing actionable after 15:00
        return None

    # ------------------------------------------------------------ signal evaluation
    def _evaluate(self, now: datetime, bar_close: datetime):
        spot = self.market.spot_1m(self.day)
        last_needed = pd.Timestamp(bar_close - timedelta(minutes=1))
        have_last = not spot.empty and (spot["ts"] == last_needed).any()
        if not have_last and now < bar_close + timedelta(seconds=self.cfg.max_candle_wait_sec):
            return  # candle not published yet, try again next tick
        if not have_last:
            self.log(f"1m candle {last_needed:%H:%M} missing; evaluating {bar_close:%H:%M} bar without it", "warn")
        if self.cfg.signal_mode == "prediction":
            return self._evaluate_prediction(now, bar_close, spot)

        bars = st.add_emas(st.resample(spot, self.cfg.timeframe))
        bars = bars[bars["close_ts"] <= pd.Timestamp(bar_close)]
        today = bars[bars["day"] == self.day]
        self.bars_today = [{"t": r.start.isoformat(), "c_ts": r.close_ts.isoformat(), "o": r.open, "h": r.high,
                            "l": r.low, "c": r.close, "e9": round(r.ema9, 2), "e21": round(r.ema21, 2)}
                           for r in today.itertuples(index=False)]
        if today.empty:
            self.log(f"No NIFTY candles for today yet (holiday?) at {bar_close:%H:%M}", "warn")
            self.processed_until = bar_close
            return
        last = today.iloc[-1]
        self.last_eval = {"bar_close": bar_close.isoformat(), "close": round(float(last["close"]), 2),
                          "ema9": round(float(last["ema9"]), 2), "ema21": round(float(last["ema21"]), 2),
                          "evaluated_at": now.isoformat()}

        legs, _ = st.generate_legs(bars, {self.day}, _hm(self.cfg.entry_start), _hm(self.cfg.cutoff))
        lo, hi = pd.Timestamp(self.processed_until), pd.Timestamp(bar_close)
        events = []
        for leg in legs:
            if leg.exit_reason == "opposite_cross" and lo < pd.Timestamp(leg.exit_ts) <= hi:
                events.append((leg.exit_ts, 0, "exit", leg))
            if lo < pd.Timestamp(leg.entry_ts) <= hi:
                events.append((leg.entry_ts, 1, "entry", leg))
        for ts, _, kind, leg in sorted(events, key=lambda e: (e[0], e[1])):
            if kind == "exit":
                if self.position:
                    self.log(f"Opposite crossover on bar closing {ts:%H:%M}: exiting")
                    self._exit("opposite_cross")
            else:
                self._try_entry(now, leg)
        self.processed_until = bar_close

    # ------------------------------------------------------------ prediction mode
    def _regime_row(self, spot: pd.DataFrame):
        if self._regime and self._regime[0] == self.day:
            return self._regime[1]
        sym = getattr(self.market, "spot_symbol", "NSE-NIFTY")
        hist = db.load_candles(sym, datetime.combine(self.day - timedelta(days=420), time(0)),
                               datetime.combine(self.day, time(0)))
        reg = signals.daily_regime(pd.concat([hist, spot[spot["ts"].dt.date == self.day]], ignore_index=True))
        row = reg.loc[self.day] if self.day in reg.index else None
        self._regime = (self.day, row)
        return row

    def _evaluate_prediction(self, now: datetime, bar_close: datetime, spot: pd.DataFrame):
        key, tf = self.cfg.strategy, self.cfg.timeframe
        fut = self.market.futures_1m(self.day) if hasattr(self.market, "futures_1m") else None
        bars = signals.signal_bars(spot, fut, tf, key)
        bars = bars[bars["close_ts"] <= pd.Timestamp(bar_close)].reset_index(drop=True)
        today = bars[bars["day"] == self.day]
        self.bars_today = [{"t": r.start.isoformat(), "c_ts": r.close_ts.isoformat(), "o": r.open, "h": r.high,
                            "l": r.low, "c": r.close, "e9": round(r.fast, 2), "e21": round(r.slow, 2)}
                           for r in today.itertuples(index=False)]
        if today.empty:
            self.log(f"No NIFTY candles for today yet (holiday?) at {bar_close:%H:%M}", "warn")
            self.processed_until = bar_close
            return
        last = today.iloc[-1]
        self.last_eval = {"bar_close": bar_close.isoformat(), "close": round(float(last["close"]), 2),
                          "ema9": round(float(last["fast"]), 2), "ema21": round(float(last["slow"]), 2),
                          "evaluated_at": now.isoformat()}
        cfg_s = strategies.STRATEGIES[key]
        lo, hi = pd.Timestamp(self.processed_until), pd.Timestamp(bar_close)
        start_t, cut_t = _hm(self.cfg.entry_start), _hm(self.cfg.cutoff)
        crosses = st.find_crosses(bars, "fast", "slow")
        for _, c in crosses.iterrows():
            ts = pd.Timestamp(c["close_ts"])
            if not (lo < ts <= hi) or c["day"] != self.day:
                continue
            ts = ts.to_pydatetime()
            if not (start_t <= ts.time() <= cut_t) or ts.time() >= st.SQUARE_OFF:
                continue
            d = int(c["direction"])
            word = "Bullish" if d > 0 else "Bearish"
            atr = float(c["atr"]) if pd.notna(c["atr"]) else float("nan")
            if not atr > 0:
                self.log(f"{word} cross at {ts:%H:%M}: ATR not available yet, no trade", "warn")
                continue
            if cfg_s.confirm and not bool(c["bull_ok"] if d > 0 else c["bear_ok"]):
                self.log(f"{word} cross at {ts:%H:%M} not confirmed by {cfg_s.confirm.upper()}: no trade")
                self._alert("HOLD", ts, direction=word, nifty=round(float(c["close"]), 2),
                            reason=f"not confirmed by {cfg_s.confirm.upper()}")
                continue
            feats, _ = signals.features(c, self._regime_row(spot), d, atr, ts)
            score = self.scorer.score(feats)
            comp = self.scorer.comparable(score)
            hist_txt = f"; past hit rate in this band {comp['hit_rate']}% (n={comp['n']})" if comp and comp["hit_rate"] is not None else ""
            entry = float(c["close"])
            stop, target = entry - d * signals.STOP_ATR * atr, entry + d * signals.TARGET_ATR * atr
            if score < self.cfg.min_score:
                self.log(f"{word} signal {ts:%H:%M} scored {score:.1f} ({signals.band(score)}){hist_txt}: below {self.cfg.min_score:g}, no trade")
                self._alert("HOLD", ts, direction=word, nifty=round(entry, 2), score=round(score, 1),
                            band=signals.band(score), reason=f"score {score:.1f} below your minimum {self.cfg.min_score:g}")
                continue
            self.log(f"{word} signal {ts:%H:%M} scored {score:.1f} ({signals.band(score)}){hist_txt}. "
                     f"NIFTY ref {entry:.2f}, stop {stop:.2f}, target {target:.2f}")
            leg = st.Leg(day=self.day, direction=d, entry_ts=ts, signal_close=entry,
                         signal_bar_start=pd.Timestamp(c["start"]).to_pydatetime(), ordinal=0)
            self._try_entry(now, leg, refs={"score": round(score, 2), "stop_ref": round(stop, 2),
                                            "target_ref": round(target, 2), "atr_ref": round(atr, 4)})
        self.processed_until = bar_close

    def _check_refs(self, now: datetime):
        """Exit at the NIFTY stop or target, judged once per completed minute."""
        minute = now.replace(second=0, microsecond=0)
        if self._ref_minute == minute:
            return
        self._ref_minute = minute
        p = self.position
        spot = self.market.spot_1m(self.day)
        day_df = spot[spot["ts"].dt.date == self.day]
        outcome, at = signals._outcome(day_df, pd.Timestamp(p["signal_ts"]).to_pydatetime(), float(p["entry_ref"]),
                                       p["direction"], float(p["atr_ref"]))
        if outcome == "hit":
            self.log(f"NIFTY reached the target {p['target_ref']:.2f} (minute {at[11:16]}): exiting")
            self._exit("target")
        elif outcome == "miss" and at:
            self.log(f"NIFTY hit the stop {p['stop_ref']:.2f} (minute {at[11:16]}): exiting", "warn")
            self._exit("stop")

    def _try_entry(self, now: datetime, leg, refs: dict | None = None):
        dirn = "Bullish" if leg.direction > 0 else "Bearish"
        if self.state in ("halted", "error"):
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} ignored: engine halted ({self.halt_reason})", "warn")
            self._hold(leg, "engine halted", **(refs or {}))
            return
        if self.position:
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} ignored: position still open", "warn")
            self._hold(leg, "a position is already open", **(refs or {}))
            return
        if (now - leg.entry_ts).total_seconds() > self.cfg.stale_entry_sec:
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} skipped: stale ({int((now - leg.entry_ts).total_seconds())}s old)", "warn")
            return
        if self.cfg.max_trades_per_day and self.trades_today >= self.cfg.max_trades_per_day:
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} skipped: daily trade limit reached", "warn")
            self._hold(leg, "daily trade limit reached", **(refs or {}))
            return
        strike, typ, side = st.option_for(self.cfg.exec_mode, leg.direction, leg.signal_close)
        expiry = st.pick_expiry(self.day, self.market.expiries(self.day), self.cfg.roll_on_expiry_day)
        if not expiry:
            self.log("No usable expiry found; entry skipped", "error")
            return
        c = self.market.contract(self.day, expiry, strike, typ)
        if not c:
            self.log(f"Contract NIFTY {expiry} {int(strike)} {typ} not found; entry skipped", "error")
            return
        qty = self.cfg.lots * c.lot_size
        self.log(f"{dirn} crossover (bar closed {leg.entry_ts:%H:%M}, NIFTY {leg.signal_close:.2f}) → "
                 f"{side} {c.trading_symbol} x{qty}")
        try:
            fill = self.broker.execute(c, side, qty, f"E{leg.entry_ts:%H%M}{self.day:%d%m}")
        except OrderUnknown as exc:
            self._halt(f"Entry order unconfirmed: {exc}", error=True)
            return
        except Exception as exc:
            self.log(f"Entry order failed: {exc}", "error")
            return
        tid = self._insert_trade({
            "session_id": self.session_id, "trade_mode": self.cfg.trade_mode, "day": self.day,
            "exec_mode": self.cfg.exec_mode, "direction": dirn, "side": side,
            "trading_symbol": c.trading_symbol, "groww_symbol": c.groww_symbol, "strike": strike,
            "opt_type": typ, "expiry": expiry, "qty": qty, "signal_ts": leg.entry_ts,
            "signal_close": leg.signal_close, "entry_ts": fill["ts"], "entry_price": fill["price"],
            "entry_order_id": fill["order_id"], "status": "OPEN", "signal_mode": self.cfg.signal_mode, **(refs or {})})
        self.position = {"id": tid, "direction": leg.direction, "side": side, "contract": c, "qty": qty,
                         "entry_price": fill["price"], "entry_ts": fill["ts"], "signal_ts": leg.entry_ts,
                         "entry_ref": leg.signal_close, **(refs or {})}
        self.trades_today += 1
        self.log(f"ENTERED {side} {c.trading_symbol} x{qty} @ {fill['price']:.2f} ({fill['order_id']})")
        r = refs or {}
        self._alert(f"{side} {typ}", leg.entry_ts, direction=dirn, nifty=round(leg.signal_close, 2), strike=strike,
                    opt_type=typ, symbol=c.trading_symbol, expiry=expiry.isoformat(), qty=qty,
                    entry_price=round(fill["price"], 2), entry_ts=pd.Timestamp(fill["ts"]).isoformat(),
                    stop=r.get("stop_ref"), target=r.get("target_ref"), score=r.get("score"),
                    band=signals.band(r["score"]) if r.get("score") is not None else None)

    # ------------------------------------------------------------ exits / risk
    def _exit(self, reason: str):
        p = self.position
        if not p:
            return
        if self.state == "error" and not reason.startswith("manual"):
            # An order outcome is unknown: never send automatic orders (could double up).
            return
        txn = "SELL" if p["side"] == "BUY" else "BUY"
        try:
            fill = self.broker.execute(p["contract"], txn, p["qty"], f"X{p['id']}{self.exit_failures}")
        except OrderUnknown as exc:
            self._halt(f"Exit order unconfirmed: {exc}. Position may still be open.", error=True)
            p["pending_reason"] = reason
            return
        except Exception as exc:
            self.exit_failures += 1
            p["pending_reason"] = reason
            self.log(f"EXIT FAILED ({self.exit_failures}): {exc}. Retrying.", "error")
            if self.exit_failures >= 5:
                self._halt("Exit failed 5 times: square off manually in the Groww app", error=True)
            return
        pnl = self._pnl(p, fill["price"])
        self._update_trade(p["id"], {"exit_ts": fill["ts"], "exit_price": fill["price"],
                                     "exit_order_id": fill["order_id"], "exit_reason": reason,
                                     "gross": pnl["gross"], "slippage": pnl["slippage"],
                                     "charges": json.dumps(pnl["charges"]), "net": pnl["net"], "status": "CLOSED"})
        self.realised_today += pnl["net"]
        self._alert("SELL" if p["side"] == "BUY" else "BUY BACK", p.get("signal_ts") or p["entry_ts"],
                    symbol=p["contract"].trading_symbol, opt_type=p["contract"].opt_type, strike=p["contract"].strike,
                    entry_price=round(p["entry_price"], 2), exit_price=round(fill["price"], 2), reason=reason,
                    net=pnl["net"], exit_ts=pd.Timestamp(fill["ts"]).isoformat())
        self.position = None
        self.exit_failures = 0
        self.log(f"EXITED {p['contract'].trading_symbol} @ {fill['price']:.2f} ({reason}) · net {pnl['net']:+,.2f}")

    def _pnl(self, p: dict, exit_price: float) -> dict:
        if self.broker.models_slippage:
            return costs.round_trip(p["side"], p["entry_price"], exit_price, p["qty"], self.cost_cfg)
        # live: prices are real fills, so only charges apply
        sign = 1 if p["side"] == "BUY" else -1
        gross = round(sign * (exit_price - p["entry_price"]) * p["qty"], 2)
        buy, sell = (p["entry_price"], exit_price) if p["side"] == "BUY" else (exit_price, p["entry_price"])
        ch = costs.charges(buy, sell, p["qty"], self.cost_cfg)
        return {"gross": gross, "slippage": 0.0, "charges": ch, "friction": ch["total"],
                "net": round(gross - ch["total"], 2)}

    def mtm(self) -> float | None:
        p = self.position
        if not p:
            return 0.0
        try:
            ltp = self.market.option_ltp(p["contract"])
        except Exception:
            return None
        self.last_ltp[p["contract"].trading_symbol] = ltp
        return self._pnl(p, ltp)["net"]

    def _risk_check(self, now: datetime):
        m = self.mtm() if self.position else 0.0      # also refreshes LTP for the UI
        if m is None or not self.cfg.max_daily_loss or self.state in ("halted", "error"):
            return
        total = self.realised_today + m
        if total <= -abs(self.cfg.max_daily_loss):
            self.log(f"Daily loss limit hit ({total:,.2f} ≤ -{self.cfg.max_daily_loss:,.0f}): squaring off", "warn")
            if self.position:
                self._exit("daily_loss_limit")
            self._halt("Daily loss limit reached: no more trades today")

    def _halt(self, reason: str, error: bool = False):
        self.state = "error" if error else "halted"
        self.halt_reason = reason
        self.log(reason, "error" if error else "warn")

    # ------------------------------------------------------------ status for UI
    def status(self) -> dict:
        with self._lock:
            pos = None
            if self.position:
                p = self.position
                c = p["contract"]
                ltp = self.last_ltp.get(c.trading_symbol)
                pos = {"trading_symbol": c.trading_symbol, "side": p["side"],
                       "direction": "Bullish" if p["direction"] > 0 else "Bearish",
                       "qty": p["qty"], "strike": c.strike, "opt_type": c.opt_type, "expiry": c.expiry.isoformat(),
                       "entry_price": p["entry_price"], "entry_ts": pd.Timestamp(p["entry_ts"]).isoformat(),
                       "ltp": ltp, "mtm": self._pnl(p, ltp)["net"] if ltp else None,
                       "exit_failures": self.exit_failures, "score": p.get("score"),
                       "stop_ref": p.get("stop_ref"), "target_ref": p.get("target_ref")}
            nxt = self._next_bar_close(self.processed_until) if self.day else None
            return {
                "state": self.state, "halt_reason": self.halt_reason, "session_id": self.session_id,
                "config": asdict(self.cfg), "now": self.market.now().isoformat(),
                "day": self.day.isoformat() if self.day else None,
                "next_eval": nxt.isoformat() if nxt else None,
                "last_eval": self.last_eval, "position": pos,
                "trades_today": self.trades_today, "realised_today": round(self.realised_today, 2),
                "nifty": {"price": self.last_spot["price"], "ts": self.last_spot["ts"].isoformat()} if self.last_spot else None,
                "conn_error": self.conn_error,
                "events": list(self.events)[:120], "bars": self.bars_today,
            }
