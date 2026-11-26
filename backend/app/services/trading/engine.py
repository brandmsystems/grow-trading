"""Live / paper / replay trading engine.

The engine re-derives today's trade sequence from CLOSED bars with exactly the
same code the backtester uses (rules.generate_legs) and acts on events it has
not processed yet. Live and backtest logic therefore cannot drift apart.

Which strategy is traded depends on the signal mode: crossover ("cross") and trend modes
always trade EMA 9/21 (rules.add_emas), whatever `strategy` says; prediction and scalp
modes use `cfg.strategy` (strategies.prepare). The Live page only offers a strategy
choice in prediction mode for that reason.

Prediction mode (signal_mode="prediction"): crosses of the chosen strategy are scored
with the Signals-page model (same features, signals.features). Only crosses scoring at
least min_score open a trade. Exits are the signal's NIFTY stop (1 x ATR) or target
(2 x ATR), judged on completed 1-minute candles exactly like the Signals outcome, or the
15:00 square-off. Opposite crosses don't exit in this mode.

Trend mode (signal_mode="trend", added 13 Nov at the user's request): at every bar close inside the
entry window, if no position is open, enter in the direction EMA 9 vs EMA 21 points (BUY CE when
EMA 9 > EMA 21, BUY PE when below), even without a fresh crossover. A position is exited when the
trend flips (the opposite crossover), then the next entry follows the new trend. All other checks
(paper risk sizing and stop, daily trade limit, daily loss limit, 15:00 square-off) are unchanged.

Scalp mode (signal_mode="scalp", 13 Nov, paper and replay only): a configuration tested on the
5-Minute Scalping page. Confirmed crossovers of the chosen strategy on completed 5-minute bars open
a trade; it exits after `hold_min` minutes ("time"), or earlier at the premium stop (stop_pct) or
target (target_pct) ("sl_target"). The premium stop is enforced in both exit rules: in "time" mode it
is a protective stop the backtest does not have (the paper risk rules require one).

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
from contextlib import contextmanager
from dataclasses import asdict, replace as dc_replace
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import text

from app.utils.timeutil import parse_hm
from app.services.notifications import alerts
from app.services.trading import charges as costs
from app.database import db
from app.services.options import sizing
from app.services.strategy import bias as biasmod
from app.services.strategy import configured
from app.services.strategy import confluence
from app.services.strategy import indicators as ind
from app.services.strategy import scanner
from app.services.strategy import signals
from app.services.strategy import strategies
from app.services.trading import paper_account
from app.services import privacy
from app.services.trading import stops
from app.services.trading import trading_settings
from app.services.trading.engine_config import EngineConfig   # re-exported: engine.EngineConfig is the public name
from app.services.strategy import rules as st
from app.services.market_data.live import Contract
from app.services.trading.brokers import OrderUnknown

log = logging.getLogger("live.engine")

MARKET_OPEN, MARKET_CLOSE = time(9, 15), time(15, 30)
STALE_PRICE_SEC = 15      # an option price older than this never triggers a paper stop-loss
SELL_MAX_DELTA = 0.6      # bias mode: a written option must not be deeper in the money than this (|delta|)


_hm = parse_hm   # kept as a module name: other modules and tests call it here


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
        self.book: list[dict] = []                 # every open position (several only for the scanner / configured entry strategies)
        self._focus: dict | None = None            # the position the per-position code (stops, exits, retries) is working on
        self.trades_today = 0
        self.realised_today = 0.0
        self.last_eval: dict | None = None
        self.last_ltp: dict = {}
        self.last_ltp_at: dict = {}               # when each LTP was read (stale prices never trigger a stop)
        self.events: deque = deque(maxlen=300)
        self._xf_idle = 0                          # exit failures counted while no position is open (always 0 in practice)
        self.bars_today: list[dict] = []
        self.last_fill_today: datetime | None = None
        self.scorer: signals.Scorer | None = None
        self._regime: tuple[date, object] | None = None
        self._ref_minute: datetime | None = None
        self.last_spot: dict | None = None        # {"ts", "price"} latest NIFTY quote
        self.pending: dict | None = None          # live entry order waiting for the user's confirmation
        self.conn_error: str | None = None
        self.last_atr: float | None = None        # NIFTY ATR of the latest signal bar (paper stop-loss)
        self.paper = self.cfg.trade_mode == "paper"
        self._last_delta: float | None = None     # |delta| behind the latest ATR stop (stored with the risk calculation)
        self._limit_day: date | None = None       # the day _limit_val was computed for
        self._limit_val = 0.0
        self.bias_state: dict | None = None       # bias mode: the latest closed-candle analysis (for the dashboard)
        self.bias_history: deque = deque(maxlen=80)
        self.rejected: deque = deque(maxlen=60)    # confluence / scored: near-miss candidates that were refused, with the reasons
        self._settings_version: int | None = None  # Trading Settings version this engine last applied (entry strategy `configured`)
        self.settings_error: str | None = None     # set while the saved Trading Settings are invalid: no entry is placed
        self._ordered: set = set()                 # (signal candle, direction) already ordered today: never ordered twice
        self._cooldown_until: datetime | None = None
        self._last_entry_signal: datetime | None = None   # signal time of the latest entry today (one entry per signal episode)
        self.paused = False                       # bias mode: no new entries while paused (open positions are still managed)
        self._no_entry_through: datetime | None = None    # bias mode: no entry on a candle closing at or before this (the candle that exited)
        self.target_hits_today = 0                # trades closed today by the net profit target
        self.strat_entry: dict[str, datetime] = {}      # scanner: signal time of each strategy's latest entry today (one entry per signal episode)
        self.strat_block: dict[str, datetime] = {}      # scanner: a strategy may not enter on a candle closing at or before this (its exit candle / cool-down)
        self.scan_state: dict | None = None        # scanner: the latest candle's opportunities, scores and decisions (dashboard)
        self.scan_rejected: deque = deque(maxlen=120)   # scanner: every refused signal with the exact reason
        self.scan_candles = 0                      # scanner: closed candles scanned this run

    # ------------------------------------------------------------ the position book
    @property
    def position(self) -> dict | None:
        """The position the code is working on: the focused one inside `_on`, else the first open one. With
        max_open_positions = 1 (every mode except the scanner) the book holds at most one, exactly as before."""
        f = self._focus
        if f is not None:
            return f if any(x is f for x in self.book) else None
        return self.book[0] if self.book else None

    @position.setter
    def position(self, value: dict | None) -> None:
        if value is None:                      # the focused (or only) position left the book
            t = self._focus if self._focus is not None else (self.book[0] if self.book else None)
            self.book = [x for x in self.book if x is not t]
        elif not any(x is value for x in self.book):
            self.book.append(value)

    @property
    def exit_failures(self) -> int:
        """Failed exit orders of the position being worked on (kept on the position, so each one retries and halts on its own)."""
        p = self.position
        return int(p.get("xf", 0)) if p else self._xf_idle

    @exit_failures.setter
    def exit_failures(self, n: int) -> None:
        p = self.position
        if p:
            p["xf"] = int(n)
        else:
            self._xf_idle = int(n)

    @contextmanager
    def _on(self, p: dict):
        """Run the existing single-position code (stop, target, trailing, time exit, retries) on one open position."""
        prev, self._focus = self._focus, p
        try:
            yield
        finally:
            self._focus = prev

    def _slots(self) -> int:
        """Concurrent positions this run may hold: the setting for the scanner and configured entry strategies, one for every other mode
        (their exit logic is written for a single position)."""
        c = self.cfg
        return c.max_open_positions if (c.signal_mode == "bias" and c.entry_strategy in ("scanner", "configured")) else 1

    @staticmethod
    def _strategy_of(p: dict) -> str | None:
        return p.get("strategy") or (p.get("analysis") or {}).get("strategy")

    def _open_risk(self, strategy: str | None = None) -> float:
        """Sum of the open positions' maximum loss (₹); of one strategy's positions when `strategy` is given."""
        return sum(float((p.get("risk") or {}).get("max_loss") or 0.0) for p in self.book
                   if strategy is None or self._strategy_of(p) == strategy)

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
        alerts.store(key, self.cfg.trade_mode, self.day, self.market.now(), action,
                     {"signal_ts": pd.Timestamp(signal_ts).isoformat(), **data}, self.session_id, self.dbe)

    def _hold(self, leg, why: str, **extra) -> None:
        if self.cfg.signal_mode == "bias" and self.cfg.entry_strategy == "scanner":
            keys = (getattr(leg, "extra", None) or {}).get("strategy_keys") or []
            self.scan_rejected.appendleft({"bar_close": pd.Timestamp(leg.entry_ts).isoformat(), "strategy": keys[0] if keys else None,
                                           "direction": "Bullish" if leg.direction > 0 else "Bearish", "reason": why})
        extra = {k: v for k, v in extra.items() if k not in ("analysis", "exec_mode", "action", "confidence")}
        self._alert("HOLD", leg.entry_ts, direction="Bullish" if leg.direction > 0 else "Bearish",
                    nifty=round(leg.signal_close, 2), reason=why, **extra)

    def _insert_trade(self, row: dict) -> int:
        row = {k: (json.dumps(v, default=str) if isinstance(v, dict) else v) for k, v in row.items()}
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
        sigs = [r["signal_ts"] for r in rows if r["signal_ts"] is not None]
        self._last_entry_signal = max(sigs) if sigs else None
        # Restart recovery for the continuous mode: the candle of the latest exit stays closed to entries, and a net
        # profit-target exit releases its signal exactly as it did before the restart.
        self.target_hits_today = sum(1 for r in rows if r["exit_reason"] == "profit_target")
        self._no_entry_through = None
        closed = sorted((r for r in rows if r["status"] == "CLOSED" and r["exit_ts"] is not None), key=lambda r: r["exit_ts"])
        if closed and self.cfg.signal_mode == "bias":
            self._no_entry_through = self._candle_close_after(pd.Timestamp(closed[-1]["exit_ts"]).to_pydatetime().replace(tzinfo=None))
            if closed[-1]["exit_reason"] == "profit_target" and self.cfg.profit_target_net > 0:
                self._last_entry_signal = None
        open_rows = [r for r in rows if r["status"] == "OPEN"]
        self.book, self._focus = [], None
        for r in (open_rows if self._slots() > 1 else open_rows[-1:]):
            self.book.append({
                "id": r["id"], "direction": 1 if r["direction"] == "Bullish" else -1, "side": r["side"],
                "contract": Contract(r["trading_symbol"], r["groww_symbol"], r["expiry"], r["strike"],
                                     r["opt_type"], r["qty"]),
                "qty": r["qty"], "entry_price": r["entry_price"], "entry_ts": r["entry_ts"],
                "signal_ts": r["signal_ts"], "entry_ref": r["signal_close"], "score": r.get("score"),
                "stop_ref": r.get("stop_ref"), "target_ref": r.get("target_ref"), "atr_ref": r.get("atr_ref"),
                "stop_premium": r.get("stop_premium"), "target_premium": r.get("target_premium"), "risk": r.get("risk"),
                "analysis": r.get("analysis"), "action": r.get("action"), "confidence": r.get("confidence"),
            })
            self.log(f"Resumed open {r['side']} position {r['trading_symbol']} x{r['qty']} from earlier", "warn")
        # scanner: each strategy's latest entry and exit candle survive a restart, so no signal is traded twice and no exit candle re-enters
        self.strat_entry, self.strat_block = {}, {}
        if self.cfg.signal_mode == "bias" and self.cfg.entry_strategy == "scanner":
            for r in rows:
                k = r["analysis"].get("strategy") if isinstance(r.get("analysis"), dict) else None
                if not k:
                    continue
                if r["signal_ts"] is not None:
                    t = pd.Timestamp(r["signal_ts"]).to_pydatetime().replace(tzinfo=None)
                    self.strat_entry[k] = max(self.strat_entry.get(k, t), t)
                if r["status"] == "CLOSED" and r["exit_ts"] is not None:
                    c = self._candle_close_after(pd.Timestamp(r["exit_ts"]).to_pydatetime().replace(tzinfo=None))
                    if c and (k not in self.strat_block or c > self.strat_block[k]):
                        self.strat_block[k] = c
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
            if square_off and self.book:
                for p in list(self.book):
                    with self._on(p):
                        self._exit("manual_stop")
                if self.book:
                    self.log("Engine stopped while a position is still open (the exit order failed or is unconfirmed): "
                             "check and close it in the broker app", "error")
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

    def pause(self) -> None:
        """Bias mode: stop taking new entries. The analysis keeps running and an open position is still managed
        (stop, profit target, 15:00 square-off); nothing is closed by pausing."""
        with self._lock:
            if self.cfg.signal_mode != "bias":
                raise ValueError("Pause is available for the automated bias engine only.")
            if not self.paused:
                self.paused = True
                self.log("Automation paused: no new entries" + (" (the open position is still managed)" if self.book else ""))

    def resume(self) -> None:
        with self._lock:
            if self.cfg.signal_mode != "bias":
                raise ValueError("Resume is available for the automated bias engine only.")
            if self.paused:
                self.paused = False
                self.log("Automation resumed: the next closed candle can open a trade")

    def square_off_now(self):
        with self._lock:
            if self.book:
                for p in list(self.book):
                    with self._on(p):
                        self._exit("manual_square_off")
            else:
                self.log("Square-off requested: no open position")

    # ------------------------------------------------------------ main loop step
    def tick(self):
        """One step of the trading loop (every second in paper/live; every 10 simulated seconds in replay).

        Order matters: refresh the spot price, expire an unconfirmed live order, then the exits
        (15:00 square-off, NIFTY stop/target, scalp time/target exits, retry of a failed exit),
        then the daily loss check and the paper premium stop, and only then evaluate a newly
        closed signal bar, so an exit is always applied before a new entry."""
        with self._lock:
            now = self.market.now()
            if self.day != now.date():
                self._new_day(now)
            self._sync_settings()
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

            if self.pending and now > self.pending["expires"]:
                self.log(f"Order {self.pending['side']} {self.pending['contract'].trading_symbol} was not confirmed "
                         f"in time: no order placed", "warn")
                self.pending = None
            for p in list(self.book):          # every open position: the single-position rules, one position at a time
                with self._on(p):
                    if self.position and now.time() >= st.SQUARE_OFF:
                        self._exit("square_off")
                    if self.position and self.position.get("stop_ref") is not None:
                        self._check_refs(now)
                    if self.position and self.cfg.signal_mode == "scalp":
                        self._scalp_exits(now)
                    if self.position and self.exit_failures:
                        self._exit(self.position.get("pending_reason", "retry"))   # retry a failed exit
            self._risk_check(now)
            for p in list(self.book):
                with self._on(p):
                    if self.position and self.cfg.signal_mode == "bias":
                        self._bias_exits(now)
                    self._premium_stop()

            nxt = self._next_bar_close(self.processed_until)
            if nxt is not None and now >= nxt + timedelta(seconds=self.cfg.bar_grace_sec):
                self._evaluate(now, nxt)

    def _new_day(self, now: datetime):
        self.day = now.date()
        self._ordered = set()
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

    def _candle_close_after(self, ts: datetime) -> datetime | None:
        """Close time of the candle that contains `ts` (the first close strictly after it)."""
        return next((c for c in self._bar_closes(ts.date()) if c > ts), None)

    def _next_bar_close(self, after: datetime | None) -> datetime | None:
        day = self.day
        for c in self._bar_closes(day):
            if after is None or c > after:
                # nothing actionable after 15:00; bias mode still analyses and predicts the remaining candles
                return c if (c.time() <= st.SQUARE_OFF or self.cfg.signal_mode == "bias") else None
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
        if self.cfg.signal_mode == "bias":
            return self._evaluate_bias(now, bar_close, spot)
        if self.cfg.signal_mode == "prediction":
            return self._evaluate_prediction(now, bar_close, spot)
        if self.cfg.signal_mode == "scalp":
            return self._evaluate_scalp(now, bar_close, spot)

        bars = st.add_emas(st.resample(spot, self.cfg.timeframe))
        bars = bars[bars["close_ts"] <= pd.Timestamp(bar_close)]
        if not bars.empty:   # paper stop-loss: NIFTY ATR of the signal timeframe, as the dashboard uses
            atr = ind.atr(bars).iloc[-1]
            self.last_atr = float(atr) if pd.notna(atr) and atr > 0 else None
        last = self._record_bars(bars, now, bar_close, "ema9", "ema21")
        if last is None:
            self.processed_until = bar_close
            return

        if self.cfg.signal_mode == "trend":
            return self._evaluate_trend(now, bar_close, last)

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

    def _record_bars(self, bars: pd.DataFrame, now: datetime, bar_close: datetime, fast: str, slow: str):
        """Publish today's closed bars and the latest evaluation for the UI. `fast`/`slow` name the EMA columns
        (ema9/ema21 in cross and trend modes, fast/slow for strategy-driven modes). Returns the last bar of
        today, or None (after logging) when there are no candles yet."""
        today = bars[bars["day"] == self.day]
        self.bars_today = [{"t": r.start.isoformat(), "c_ts": r.close_ts.isoformat(), "o": r.open, "h": r.high,
                            "l": r.low, "c": r.close, "e9": round(getattr(r, fast), 2), "e21": round(getattr(r, slow), 2)}
                           for r in today.itertuples(index=False)]
        if today.empty:
            self.log(f"No NIFTY candles for today yet (holiday?) at {bar_close:%H:%M}", "warn")
            return None
        last = today.iloc[-1]
        self.last_eval = {"bar_close": bar_close.isoformat(), "close": round(float(last["close"]), 2),
                          "ema9": round(float(last[fast]), 2), "ema21": round(float(last[slow]), 2),
                          "evaluated_at": now.isoformat()}
        return last

    def _window_crosses(self, bars: pd.DataFrame, lo, bar_close: datetime):
        """Crossovers of fast/slow that closed in (lo, bar_close], today, inside the entry window and before the
        15:00 square-off. Yields (close time, row, direction, "Bullish"/"Bearish")."""
        hi, lo = pd.Timestamp(bar_close), pd.Timestamp(lo)
        start_t, cut_t = _hm(self.cfg.entry_start), _hm(self.cfg.cutoff)
        for _, c in st.find_crosses(bars, "fast", "slow").iterrows():
            ts = pd.Timestamp(c["close_ts"])
            if not (lo < ts <= hi) or c["day"] != self.day:
                continue
            ts = ts.to_pydatetime()
            if not (start_t <= ts.time() <= cut_t) or ts.time() >= st.SQUARE_OFF:
                continue
            d = int(c["direction"])
            yield ts, c, d, "Bullish" if d > 0 else "Bearish"

    # ------------------------------------------------------------ trend mode
    def _evaluate_trend(self, now: datetime, bar_close: datetime, last) -> None:
        """Enter whenever EMA 9 and EMA 21 agree on a direction; exit when they flip."""
        self.processed_until = bar_close
        e9, e21 = float(last["ema9"]), float(last["ema21"])
        if pd.Timestamp(last["close_ts"]) != pd.Timestamp(bar_close) or not (e9 == e9 and e21 == e21) or e9 == e21:
            return
        d = 1 if e9 > e21 else -1
        word = "up (EMA 9 above EMA 21)" if d > 0 else "down (EMA 9 below EMA 21)"
        if self.position and self.position["direction"] != d:
            self.log(f"Trend flipped {word} on bar closing {bar_close:%H:%M}: exiting")
            self._exit("opposite_cross")
        t = bar_close.time()
        if not (_hm(self.cfg.entry_start) <= t <= _hm(self.cfg.cutoff)) or t >= st.SQUARE_OFF:
            return
        if self.position:
            self.log(f"{bar_close:%H:%M} trend {word}: position already open, holding")
            return
        self.log(f"{bar_close:%H:%M} trend {word}: entering")
        leg = st.Leg(day=self.day, direction=d, entry_ts=bar_close, signal_close=float(last["close"]),
                     signal_bar_start=pd.Timestamp(last["start"]).to_pydatetime(), ordinal=self.trades_today + 1)
        self._try_entry(now, leg)

    # ------------------------------------------------------------ scalp mode
    def _evaluate_scalp(self, now: datetime, bar_close: datetime, spot: pd.DataFrame) -> None:
        """Confirmed crossovers of the chosen strategy on completed 5-minute bars (as the scalping analyzer)."""
        key = self.cfg.strategy
        fut = None
        if strategies.STRATEGIES[key].confirm == "vwap" and hasattr(self.market, "futures_1m"):
            fut = self.market.futures_1m(self.day)
        bars = strategies.prepare(spot, fut, self.cfg.timeframe, key)
        bars = bars[bars["close_ts"] <= pd.Timestamp(bar_close)].reset_index(drop=True)
        lo = pd.Timestamp(self.processed_until)
        self.processed_until = bar_close
        if self._record_bars(bars, now, bar_close, "fast", "slow") is None:
            return
        s = strategies.STRATEGIES[key]
        for ts, c, d, word in self._window_crosses(bars, lo, bar_close):
            if s.confirm and not bool(c["bull_ok"] if d > 0 else c["bear_ok"]):
                self.log(f"{word} {s.label} cross at {ts:%H:%M} not confirmed by {s.confirm.upper()}: no trade")
                continue
            self.log(f"{word} {s.label} cross on the 5-min bar closing {ts:%H:%M}: scalp entry")
            leg = st.Leg(day=self.day, direction=d, entry_ts=ts, signal_close=float(c["close"]),
                         signal_bar_start=pd.Timestamp(c["start"]).to_pydatetime(), ordinal=0)
            self._try_entry(now, leg)

    def _scalp_exits(self, now: datetime) -> None:
        """Time exit hold_min minutes after the fill; premium target exit (sl_target). In paper mode the
        stop is _premium_stop (levels from the risk calculation). Replay has no paper risk sizing, so its
        stop and target are set from the entry fill and both are checked here."""
        p = self.position
        if not p or p.get("exiting"):
            return
        entered = pd.Timestamp(p["entry_ts"]).to_pydatetime().replace(tzinfo=None)
        if (now - entered).total_seconds() >= self.cfg.hold_min * 60:
            self.log(f"Held {self.cfg.hold_min} min: time exit")
            self._exit("time_exit")
            return
        sym = p["contract"].trading_symbol
        if not self.paper:
            if p.get("stop_premium") is None and not p.get("scalp_levels_set"):
                stop, tgt, how, _ = self._paper_stop(p["contract"], p["side"], float(p["entry_price"]))
                p.update(stop_premium=stop, target_premium=tgt, scalp_levels_set=True)
                self._update_trade(p["id"], {"stop_premium": stop, "target_premium": tgt})
                self.log(f"Scalp levels from the fill {p['entry_price']:.2f}: {how}")
            try:
                self.last_ltp[sym], self.last_ltp_at[sym] = float(self.market.option_ltp(p["contract"])), self.market.now()
            except Exception:
                return
        ltp, at = self.last_ltp.get(sym), self.last_ltp_at.get(sym)
        if ltp is None or at is None or (self.market.now() - at).total_seconds() > STALE_PRICE_SEC:
            return
        buy = p["side"] == "BUY"
        stop = p.get("stop_premium")
        if not self.paper and stop is not None and ((ltp <= stop) if buy else (ltp >= stop)):
            self.log(f"Premium {ltp:.2f} reached the stop-loss {stop:.2f}: exiting", "warn")
            self._exit("stop_loss")
            return
        tgt = p.get("target_premium")
        if self.cfg.scalp_exit == "sl_target" and tgt is not None:
            if (ltp >= tgt) if buy else (ltp <= tgt):
                self.log(f"Premium {ltp:.2f} reached the target {tgt:.2f}: exiting")
                self._exit("target")

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
        if self._record_bars(bars, now, bar_close, "fast", "slow") is None:
            self.processed_until = bar_close
            return
        cfg_s = strategies.STRATEGIES[key]
        for ts, c, d, word in self._window_crosses(bars, pd.Timestamp(self.processed_until), bar_close):
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
            self.last_atr = atr
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

    # ------------------------------------------------------------ Trading Settings (the centrally managed configuration)
    def _sync_settings(self) -> None:
        """Entry strategy `configured`: re-read the saved Trading Settings every tick and, when the version changed, apply them to this
        engine's configuration (validated as a whole; a bad configuration changes nothing and blocks entries). No restart needed."""
        if self.cfg.entry_strategy not in ("configured", "scanner") or self.cfg.signal_mode != "bias":
            return
        res = trading_settings.current()
        if res.error:
            if self.settings_error != res.error:
                self.log(f"Trading Settings are invalid or unreadable ({res.error}): no order will be placed until they are fixed", "error")
            self.settings_error = f"the saved Trading Settings are invalid or unreadable ({res.error})"
            return
        if res.version == self._settings_version and not self.settings_error:
            return
        try:
            new = dc_replace(self.cfg, **res.engine_overrides()).validate()
        except ValueError as exc:
            self.settings_error = f"Trading Settings version {res.version} cannot be applied: {exc}"
            self.log(self.settings_error, "error")
            return
        old, self.cfg, self.settings_error = self.cfg, new, None
        diff = [f"{k}: {getattr(old, k)} → {getattr(new, k)}" for k in res.engine_overrides()
                if k != "ind" and getattr(old, k) != getattr(new, k)]
        first = self._settings_version is None
        self._settings_version = res.version
        self._limit_day = None
        self.log(f"Trading Settings version {res.version} {'loaded' if first else 'applied'}" + (": " + "; ".join(diff[:12]) if diff and not first else ""))
        if self.session_id:
            try:
                with self.dbe.begin() as c:
                    c.execute(text("UPDATE live_sessions SET config=CAST(:c AS JSONB) WHERE id=:i"), {"c": json.dumps(asdict(new)), "i": self.session_id})
            except Exception:
                log.warning("session configuration not updated", exc_info=True)

    def _legacy_keys(self) -> list[str]:
        """The registry strategy an engine trades when the signal does not name one (everything except the `configured` strategy)."""
        m = self.cfg.signal_mode
        if m in ("prediction", "scalp"):
            return [self.cfg.strategy]
        if m == "bias":
            return [self.cfg.entry_strategy] if self.cfg.entry_strategy in ("bias", "confluence", "scored") else ["bias"]
        return ["ema_9_21"]                       # the cross and trend modes always trade EMA 9/21

    def _settings_gate(self, leg):
        """(reason to refuse | None, settings, strategy keys). An order needs: valid saved settings, at least one strategy behind the signal,
        every such strategy ON and not blocked by a disabled indicator, and an enabled timeframe. Applies to every mode."""
        res = trading_settings.current()
        keys = list((getattr(leg, "extra", None) or {}).get("strategy_keys") or self._legacy_keys())
        if res.error:
            return f"the saved Trading Settings are invalid or unreadable ({res.error}); no order is placed", res, keys
        if self.settings_error:
            return self.settings_error, res, keys
        if not keys:
            return "no enabled strategy is behind this signal", res, keys
        for k in keys:
            reg = trading_settings.STRATEGIES.get(k)
            if reg is None:
                return f"unknown strategy '{k}'", res, keys
            if not res.strategy_enabled(k):
                return f"{reg['label']} is switched OFF in Trading Settings", res, keys
            if res.blockers(k):
                return f"{reg['label']} is blocked: {'; '.join(res.blockers(k))}", res, keys
        if not res.timeframe_enabled(self.cfg.timeframe):
            return f"the {self.cfg.timeframe}-minute timeframe is disabled in Trading Settings", res, keys
        return None, res, keys

    def _with_settings(self, refs: dict | None, res, keys: list[str], leg) -> dict:
        """The order's record of what it was placed under: strategy, timeframes, enabled indicators, settings version, and the entry reason."""
        refs = dict(refs or {})
        a = dict(refs.get("analysis") or {})
        a["settings"] = {**res.snapshot(keys), "engine_timeframe": self.cfg.timeframe}
        a.setdefault("strategy", keys[0] if keys else None)
        if not a.get("summary"):
            label = trading_settings.STRATEGIES.get(keys[0], {}).get("label", keys[0]) if keys else "signal"
            a["summary"] = f"{label}: {'BUY CE' if leg.direction > 0 else 'BUY PE'} signal on the {self.cfg.timeframe}-minute candle closing {leg.entry_ts:%H:%M}"
        refs["analysis"] = a
        return refs

    def _try_entry(self, now: datetime, leg, refs: dict | None = None):
        dirn = "Bullish" if leg.direction > 0 else "Bearish"
        if self.state in ("halted", "error"):
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} ignored: engine halted ({self.halt_reason})", "warn")
            self._hold(leg, "engine halted", **(refs or {}))
            return
        why, res, keys = self._settings_gate(leg)
        if why:
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M}: NO ORDER. {why}", "warn")
            self._hold(leg, f"trading settings: {why}", **(refs or {}))
            return
        refs = self._with_settings(refs, res, keys, leg)
        okey = (pd.Timestamp(leg.entry_ts), leg.direction, tuple(keys))
        if okey in self._ordered:
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} ignored: an order was already placed from this candle", "warn")
            self._hold(leg, "an order was already placed from this signal", **(refs or {}))
            return
        if len(self.book) >= self._slots():
            many = self._slots() > 1
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} ignored: "
                     + (f"{len(self.book)} positions open (maximum {self._slots()})" if many else "position still open"), "warn")
            self._hold(leg, f"the maximum of {self._slots()} open positions is reached" if many else "a position is already open", **(refs or {}))
            return
        if self._slots() > 1 and keys:
            same = sum(1 for x in self.book if self._strategy_of(x) == keys[0])
            if same >= self.cfg.max_strategy_positions:
                self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} ignored: {keys[0]} already holds {same} position(s) "
                         f"(maximum {self.cfg.max_strategy_positions} per strategy)", "warn")
                self._hold(leg, f"this strategy already holds {same} position(s) (maximum {self.cfg.max_strategy_positions})", **(refs or {}))
                return
        if (now - leg.entry_ts).total_seconds() > self.cfg.stale_entry_sec:
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} skipped: stale ({int((now - leg.entry_ts).total_seconds())}s old)", "warn")
            return
        if self.cfg.max_trades_per_day and self.trades_today >= self.cfg.max_trades_per_day:
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M} skipped: daily trade limit reached", "warn")
            self._hold(leg, "daily trade limit reached", **(refs or {}))
            return
        strike, typ, side = st.option_for((refs or {}).get("exec_mode") or self.cfg.exec_mode, leg.direction, leg.signal_close)
        expiry = st.pick_expiry(self.day, self.market.expiries(self.day), self.cfg.roll_on_expiry_day)
        if not expiry:
            self.log("No usable expiry found; entry skipped", "error")
            return
        c = self.market.contract(self.day, expiry, strike, typ)
        if not c:
            self.log(f"Contract NIFTY {expiry} {int(strike)} {typ} not found; entry skipped", "error")
            return
        pm = self._premarket(leg.direction)
        if pm and pm["agrees"] is False and self.cfg.premarket_mode == "block_opposed":
            self.log(f"{dirn} signal at {leg.entry_ts:%H:%M}: NO TRADE. The pre-market bias ({pm['bias']}, {pm['total']:+d}) opposes it "
                     f"(setting: block opposed trades)", "warn")
            self._hold(leg, f"pre-market bias {pm['bias']} opposes this trade")
            return
        if pm:
            refs = {**(refs or {}), "analysis": {**((refs or {}).get("analysis") or {}), "premarket": pm}}
        if self.cfg.signal_mode == "bias":
            why = self._bias_contract_check(c, side, refs)
            if why:
                self.log(f"{dirn} signal at {leg.entry_ts:%H:%M}: NO TRADE. {why}", "warn")
                self._hold(leg, f"contract check: {why}")
                return
            if self.cfg.entry_strategy == "scanner":
                why = self._scan_finalize(c, side, refs, keys[0] if keys else None)
                if why:
                    self.log(f"{dirn} signal at {leg.entry_ts:%H:%M}: NO TRADE. {why}", "warn")
                    self._hold(leg, why)
                    return
        if self.paper:
            risk = self._paper_risk(leg, c, side)
            if risk["decision"] != "TRADE":
                self.log(f"{dirn} signal at {leg.entry_ts:%H:%M}: NO TRADE. {risk['reason']}", "warn")
                self._hold(leg, f"risk check: {risk['reason']}", risk=risk, **(refs or {}))
                return
            qty = risk["qty"]
            refs = {**(refs or {}), "risk": risk, "stop_premium": risk["stop"], "target_premium": risk.get("target"),
                    "paper_account_id": risk["account_id"]}
            self.log(f"Risk: {risk['risk_pct']:g}% of ₹{risk['capital']:,.0f} = ₹{risk['risk_amount']:,.0f}; "
                     f"premium {risk['entry']:.2f}, stop {risk['stop']:.2f}, risk/lot ₹{risk['risk_per_lot']:,.0f} → "
                     f"{risk['lots']} lot(s) × {risk['lot_size']} = {qty}; max loss ₹{risk['max_loss']:,.0f}")
        else:
            qty = self.cfg.lots * c.lot_size
        if self.cfg.trade_mode == "live" and self.cfg.order_confirmation == "manual":
            self._propose(now, leg, c, side, qty, strike, typ, expiry, refs)
            return
        n_before = self.trades_today
        self._execute_entry(leg, c, side, qty, strike, typ, expiry, refs)
        if self.trades_today > n_before:
            self._ordered.add(okey)

    def _premarket(self, direction: int) -> dict | None:
        """The stored pre-market report's view of this trade (agrees / opposes / no view), or None. Read-only information:
        it never creates an entry, and it blocks one only when premarket_mode is block_opposed."""
        if self.cfg.premarket_mode == "off" or self.cfg.trade_mode == "live":
            return None
        try:
            from app.services.premarket import service as premarket
            return premarket.stamp(self.day, direction, self.dbe)
        except Exception as exc:
            self.log(f"Pre-market stamp unavailable: {exc}", "warn")
            return None

    # ------------------------------------------------------------ paper risk management
    def _paper_stop(self, c, side: str, premium: float) -> tuple[float | None, float | None, str, str | None]:
        """(stop premium, target premium, method text, error). See stops.stop_levels."""
        lv = stops.stop_levels(self.cfg, side, premium, self.last_atr, lambda: self.market.option_delta(c))
        self._last_delta = lv.delta
        return lv.stop, lv.target, lv.how, lv.error

    def _paper_risk(self, leg, c, side: str) -> dict:
        """Steps 1-10 of the paper risk rules: capital, risk %, premium, stop, risk per lot, lots, then
        the daily-loss, balance, lot and open-position checks. Returns the full calculation."""
        acct = paper_account.state(self.day, self.cfg, positions=list(self.book) or None, mtm=self._book_mtm(), eng=self.dbe)
        base = {"account_id": acct["account_id"], "balance": acct["balance"],
                "day_start_capital": acct["day_start_capital"], "daily_limit": acct["daily_limit"],
                "pnl_today": acct["pnl_today"], "contract": c.trading_symbol, "signal_ts": leg.entry_ts.isoformat()}
        try:
            premium = round(float(self.market.option_ltp(c)), 2)
        except Exception as exc:
            premium = None
            base["premium_error"] = str(exc)
        stop = target = None
        how, err = "", None
        if premium:
            stop, target, how, err = self._paper_stop(c, side, premium)
        if acct["available"] <= 0:
            r = {"decision": "NO TRADE", "reason": f"No virtual capital available (₹{acct['available']:,.2f}).",
                 "capital": acct["available"], "risk_pct": self.cfg.risk_pct, "entry": premium, "stop": stop,
                 "lot_size": c.lot_size, "lots": 0, "qty": 0}
        else:
            rp = self.cfg.sell_risk_pct if (side == "SELL" and self.cfg.signal_mode == "bias") else self.cfg.risk_pct
            r = sizing.risk_size(side, premium, stop, c.lot_size, acct["available"], rp,
                                 available=acct["available"], max_lots=self.cfg.max_lots,
                                 min_balance=self.cfg.min_balance, target=target, cfg=self.cost_cfg,
                                 include_slippage=True)
        r.update(base, stop_method=how, stop_mode=self.cfg.stop_mode, delta=self._last_delta,
                 atr=self.last_atr, nifty_ref=round(leg.signal_close, 2))
        if err:
            r.update(decision="NO TRADE", reason=err)
        with self.dbe.connect() as cx:
            open_n = cx.execute(text("SELECT count(*) FROM live_trades WHERE trade_mode='paper' AND status='OPEN'")).scalar()
        within_daily = r["decision"] != "TRADE" or acct["daily_limit"] is None or r["max_loss"] <= acct["remaining_risk"]
        r["checks"] = {
            "premium_and_stop": bool(premium) and stop is not None and not err,
            "one_lot_within_risk": (r.get("lots_by_risk") or 0) > 0,
            "available_balance": r.get("lots_by_cash") is None or r["lots_by_cash"] > 0,
            "max_lots": r.get("lots", 0) <= self.cfg.max_lots,
            "daily_loss_limit": not acct["limit_reached"],
            "remaining_daily_risk": within_daily,
            "open_positions": open_n < self.cfg.max_open_positions,
        }
        key = ((getattr(leg, "extra", None) or {}).get("strategy_keys") or [None])[0]
        if r["decision"] == "TRADE" and self._slots() > 1:
            new_loss, cap = float(r["max_loss"]), float(acct["balance"])
            tot, own = self._open_risk(), self._open_risk(key)
            r["portfolio"] = {"open_risk": round(tot, 2), "new_risk": round(new_loss, 2), "strategy_open_risk": round(own, 2), "capital": round(cap, 2),
                              "open_positions": len(self.book)}
            r["checks"]["total_open_risk"] = not (self.cfg.max_open_risk_pct > 0 and tot + new_loss > cap * self.cfg.max_open_risk_pct / 100)
            r["checks"]["strategy_open_risk"] = not (self.cfg.max_strategy_risk_pct > 0 and own + new_loss > cap * self.cfg.max_strategy_risk_pct / 100)
        problems = []
        if not r["checks"].get("total_open_risk", True):
            problems.append(f"Total open risk would be ₹{tot + new_loss:,.0f} (₹{tot:,.0f} open + ₹{new_loss:,.0f} new), above the limit of "
                            f"{self.cfg.max_open_risk_pct:g}% of capital (₹{cap * self.cfg.max_open_risk_pct / 100:,.0f}).")
        if not r["checks"].get("strategy_open_risk", True):
            problems.append(f"This strategy's open risk would be ₹{own + new_loss:,.0f}, above its limit of {self.cfg.max_strategy_risk_pct:g}% "
                            f"of capital (₹{cap * self.cfg.max_strategy_risk_pct / 100:,.0f}).")
        if acct["limit_reached"]:
            problems.append(f"Daily loss limit reached (today {acct['pnl_today']:,.2f} ≤ -{acct['daily_limit']:,.0f}).")
        if open_n >= self.cfg.max_open_positions:
            problems.append(f"{open_n} paper position(s) already open (maximum {self.cfg.max_open_positions}).")
        if not within_daily:
            problems.append(f"Maximum loss ₹{r['max_loss']:,.0f} exceeds the ₹{acct['remaining_risk']:,.0f} "
                            f"left in today's loss limit.")
        if problems:   # record every failed check, not just the first
            first = [r["reason"]] if r["decision"] != "TRADE" and r.get("reason") else []
            r.update(decision="NO TRADE", reason=" ".join(first + problems))
        r["calculated_at"] = self.market.now().isoformat()
        return r

    def _premium_stop(self):
        """Paper trades exit when the option premium reaches the stop-loss (checked every tick)."""
        p = self.position
        if not (self.paper and p and p.get("stop_premium") is not None):
            return
        if p.get("exiting"):
            return
        sym = p["contract"].trading_symbol
        ltp, at = self.last_ltp.get(sym), self.last_ltp_at.get(sym)
        if ltp is None or at is None:
            return
        age = (self.market.now() - at).total_seconds()
        if age > STALE_PRICE_SEC:      # never act on an old price; the next fresh quote is checked
            if not p.get("stale_warned"):
                self.log(f"Option premium is {age:.0f}s old: stop-loss not checked until a fresh price arrives", "warn")
                p["stale_warned"] = True
            return
        p["stale_warned"] = False
        hit = ltp <= p["stop_premium"] if p["side"] == "BUY" else ltp >= p["stop_premium"]
        if hit:
            self.log(f"Premium {ltp:.2f} reached the stop-loss {p['stop_premium']:.2f}: exiting", "warn")
            p["exiting"] = True
            self._exit("stop_loss")
            if self.position is p:      # exit failed: the retry path handles it, never a second stop exit at once
                p["exiting"] = False

    # ------------------------------------------------------------ bias mode (paper / replay only)
    def _scope(self) -> int:
        return (self.session_id or 0) if self.cfg.trade_mode == "replay" else 0

    def _store_prediction(self, r: pd.Series, expl: dict, backfilled: bool = False) -> None:
        """Record the analysis of one closed 5m candle and its prediction for the next candle."""
        votes = {"5m": {k: biasmod._v(r.get(f"v5_{k}")) for k in biasmod.INDICATORS},
                 "15m": {k: biasmod._v(r.get(f"v15_{k}")) for k in biasmod.INDICATORS}}
        try:
            with self.dbe.begin() as c:
                c.execute(text(
                    "INSERT INTO candle_bias (trade_mode, scope, day, bar_close, nifty_close, bias, confidence, score_5m, "
                    "score_15m, combined, signal, predicted, votes, analysis) VALUES (:m,:sc,:d,:t,:px,:b,:cf,:s5,:s15,:cb,:sg,"
                    ":pr,CAST(:v AS JSONB),CAST(:a AS JSONB)) ON CONFLICT (trade_mode, scope, bar_close) DO NOTHING"),
                    {"m": self.cfg.trade_mode, "sc": self._scope(), "d": self.day,
                     "t": pd.Timestamp(r["close_ts"]).to_pydatetime(),
                     "px": expl["close"], "b": expl["bias"], "cf": expl["confidence"], "s5": expl["score_5m"],
                     "s15": expl["score_15m"], "cb": expl["combined"], "sg": expl["signal"], "pr": expl["prediction"],
                     "v": json.dumps(votes),
                     "a": json.dumps({**expl, **({"backfilled": True} if backfilled else {})}, default=str)})
        except Exception as exc:
            log.warning("prediction not stored: %s", exc)

    def _settle_prediction(self, prev: pd.Series, nxt: pd.Series, p: "biasmod.BiasParams") -> str | None:
        """The candle after `prev` has closed: record what actually happened and whether the prediction was right."""
        actual = biasmod.classify(float(nxt["close"]) - float(prev["close"]), float(prev["atr"]), p.flat_atr)
        outcome = biasmod.classify_outcome(prev["predicted"], actual)
        try:
            with self.dbe.begin() as c:
                c.execute(text("UPDATE candle_bias SET next_close=:n, actual=:a, outcome=:o, settled_at=now() "
                               "WHERE trade_mode=:m AND scope=:sc AND bar_close=:t AND outcome IS NULL"),
                          {"n": float(nxt["close"]), "a": actual, "o": outcome, "m": self.cfg.trade_mode,
                           "sc": self._scope(), "t": pd.Timestamp(prev["close_ts"]).to_pydatetime()})
        except Exception as exc:
            log.warning("prediction outcome not stored: %s", exc)
        return outcome

    def _evaluate_bias(self, now: datetime, bar_close: datetime, spot: pd.DataFrame) -> None:
        """Analyse the 5m candle that just closed (confirmed by the 15m trend), log the prediction for the next
        candle, settle the previous prediction, then manage the position and look for an entry. Closed candles only."""
        cfg = self.cfg
        try:
            fut = self.market.futures_1m(self.day) if hasattr(self.market, "futures_1m") else None
        except Exception as exc:
            fut = None
            self.log(f"Futures data unavailable ({exc}): VWAP and volume cannot vote this candle", "warn")
        try:
            p = biasmod.BiasParams.from_cfg(cfg)
            frame = biasmod.analyse(spot, fut, p)
            cp = confluence.params_for(cfg)
            if cp is not None:      # same bars and same rules path; only the entry decision comes from the confluence / scored strategy
                frame = confluence.overlay(frame, spot, fut, cp)
            if not frame.empty:
                frame = frame[frame["close_ts"] <= pd.Timestamp(bar_close)].reset_index(drop=True)
            cres = cinfo = None
            if cfg.entry_strategy in ("configured", "scanner") and not frame.empty:     # the strategies that are ON in Trading Settings decide
                cres = trading_settings.current()
                frame, cinfo = configured.evaluate(cres, spot, fut, frame, cfg, bar_close)
            today = frame[frame["day"] == self.day] if not frame.empty else frame
        except Exception as exc:
            self.processed_until = bar_close
            self.log(f"Bias analysis failed at {bar_close:%H:%M}: {exc}", "error")
            log.error(traceback.format_exc())
            return
        self.processed_until = bar_close
        if today.empty:
            self.log(f"No NIFTY candles for today yet (holiday?) at {bar_close:%H:%M}", "warn")
            return
        r = today.iloc[-1]
        self.bars_today = [{"t": x.start.isoformat(), "c_ts": x.close_ts.isoformat(), "o": x.open, "h": x.high, "l": x.low,
                            "c": x.close, "e9": round(x.ema9, 2), "e21": round(x.ema21, 2)}
                           for x in today.itertuples(index=False)]
        if pd.Timestamp(r["close_ts"]) != pd.Timestamp(bar_close):
            self.log(f"{cfg.timeframe}m candle closing {bar_close:%H:%M} is missing: no decision on this candle", "warn")
            return
        def explain_row(row: pd.Series, last: bool = False) -> dict:
            e = biasmod.explain(row, p)
            if cinfo is not None:
                return configured.explain(e, cinfo, cres) if last else e
            return confluence.explain(row, cp, e) if cp is not None else e

        expl = explain_row(r, True)
        self.last_atr = float(r["atr"]) if pd.notna(r["atr"]) and r["atr"] > 0 else None
        self.last_eval = {"bar_close": bar_close.isoformat(), "close": expl["close"], "ema9": round(float(r["ema9"]), 2),
                          "ema21": round(float(r["ema21"]), 2), "evaluated_at": now.isoformat()}
        self.bias_state = expl
        if not self.bias_history:        # first analysis of this run: record the earlier candles of today too
            for i in range(len(today) - 1):
                row = today.iloc[i]
                self._store_prediction(row, explain_row(row), backfilled=True)
                if i:
                    self._settle_prediction(today.iloc[i - 1], row, p)
            if len(today) >= 2:
                self._settle_prediction(today.iloc[-2], r, p)
        else:
            outcome = self._settle_prediction(today.iloc[-2], r, p) if len(today) >= 2 else None
            if outcome:
                self.bias_history[0]["outcome"] = outcome
        self._store_prediction(r, expl)
        blk = expl.get("scored") or expl.get("confluence") or {}
        if cp is not None and expl["direction"] == 0 and blk.get("candidate") and expl["entry_score"] >= 0.8 * blk["min_score"]:
            # a near miss (at least 80% of the minimum score) that was refused: kept for the dashboard with its reasons
            self.rejected.appendleft({"bar_close": expl["bar_close"], "side": blk["candidate"], "score": expl["entry_score"],
                                      "min_score": blk["min_score"], "reasons": blk.get("rejections", [])})
        self.bias_history.appendleft({"bar_close": expl["bar_close"], "close": expl["close"], "bias": expl["bias"],
                                      "confidence": expl["confidence"], "signal": expl["signal"],
                                      "predicted": expl["prediction"], "score_5m": expl["score_5m"],
                                      "score_15m": expl["score_15m"], "outcome": None})
        self.log(f"{bar_close:%H:%M} {expl['summary']}")

        if cfg.entry_strategy == "scanner":
            return self._scan_and_trade(now, bar_close, r, expl, cinfo)
        d = int(r["direction"])
        opposite = d != 0 and bool(self.position) and d != self.position["direction"]
        if self.position and cinfo is not None and cres.exit_role == "trend":
            # exit confirmation on the trend timeframe: its score turning clearly against the position (not just any opposite entry signal)
            s15 = r["s15"]
            opposite = bool(pd.notna(s15) and abs(float(s15)) >= cfg.bias_trend_thr and (float(s15) > 0) != (self.position["direction"] > 0))
        if self.position and cfg.bias_exit_opposite and opposite:
            self.log(f"{bar_close:%H:%M} the analysis now points the other way ({expl['signal']}): exiting; "
                     f"no reversal trade, the next candle gets a fresh analysis")
            self._exit("opposite_signal")
            self._cooldown_until = bar_close + timedelta(minutes=5 * cfg.bias_cooldown_bars)
            return
        if d == 0:
            if expl["hold_reasons"]:
                self.log(f"{bar_close:%H:%M} HOLD: " + "; ".join(expl["hold_reasons"]))
            return
        t = bar_close.time()
        if self.position:
            self.log(f"{bar_close:%H:%M} {expl['signal']} candidate ignored: position already open (holding)")
            return
        if self.paused:
            self.log(f"{bar_close:%H:%M} {expl['signal']} candidate not traded: automation is paused (no new entries)")
            return
        if self._no_entry_through and bar_close <= self._no_entry_through:
            self.log(f"{bar_close:%H:%M} {expl['signal']} candidate skipped: this candle contains the last exit; "
                     f"the next entry needs a later candle")
            return
        if not (_hm(cfg.entry_start) <= t <= _hm(cfg.cutoff)) or t >= st.SQUARE_OFF:
            self.log(f"{bar_close:%H:%M} {expl['signal']} candidate outside the entry window "
                     f"{cfg.entry_start}-{cfg.cutoff}: no trade")
            return
        if self._cooldown_until and bar_close < self._cooldown_until:
            self.log(f"{bar_close:%H:%M} {expl['signal']} candidate skipped: cooling down until "
                     f"{self._cooldown_until:%H:%M} after the last exit")
            return
        # one entry per signal episode: the run of consecutive candles that all point the same way. After an exit
        # (stop, target, time) the same unchanged signal does not re-enter; it has to lapse and form again.
        run = today["direction"].to_numpy()
        i = len(run) - 1
        while i > 0 and run[i - 1] == d:
            i -= 1
        episode_start = pd.Timestamp(today.iloc[i]["close_ts"]).to_pydatetime()
        if self._last_entry_signal is not None and pd.Timestamp(self._last_entry_signal) >= pd.Timestamp(episode_start):
            self.log(f"{bar_close:%H:%M} {expl['signal']} candidate skipped: this signal (running since {episode_start:%H:%M}) "
                     f"was already traded; waiting for a new one")
            return
        pick = self._bias_pick(d)
        if pick is None:
            self.log(f"{bar_close:%H:%M} {expl['signal']} candidate: {'CE' if d > 0 else 'PE'} trades are not "
                     f"enabled in your settings", "warn")
            return
        mode, side, typ = pick
        expl = {**expl, "instrument": f"{side} {typ}"}
        leg = st.Leg(day=self.day, direction=d, entry_ts=bar_close, signal_close=float(r["close"]),
                     signal_bar_start=pd.Timestamp(r["start"]).to_pydatetime(), ordinal=self.trades_today + 1,
                     extra={"strategy_keys": list(cinfo["fired"])} if cinfo is not None else {})
        n_before = self.trades_today
        self._try_entry(now, leg, refs={"exec_mode": mode, "action": f"{side} {typ}", "confidence": expl.get("entry_score", expl["confidence"]),
                                        "analysis": expl})
        if self.trades_today > n_before:
            self._last_entry_signal = bar_close

    # ------------------------------------------------------------ continuous opportunity scanner (paper / replay only)
    def _scan_reject(self, o: dict, bar_close, reason: str) -> None:
        o["decision"], o["reasons"] = "REJECTED", [*o["reasons"], reason]
        self.scan_rejected.appendleft({"bar_close": pd.Timestamp(bar_close).isoformat(), "strategy": o["strategy"],
                                       "direction": "Bullish" if o["direction"] > 0 else "Bearish", "reason": reason,
                                       "quality": o.get("quality")})

    def _scan_and_trade(self, now: datetime, bar_close: datetime, r: pd.Series, expl: dict, cinfo: dict | None) -> None:
        """One closed candle: look at every strategy on its own, rank the qualified opportunities by quality score and take each one
        that every rule allows. Opposite-signal exits are per strategy. Nothing is forced: no candidate, no trade."""
        cfg = self.cfg
        self.scan_candles += 1
        res = scanner.scan(cinfo, r, cfg, bar_close)
        opps, by = res["opps"], res["by_key"]
        if cfg.bias_exit_opposite:
            for p in list(self.book):
                o = by.get(self._strategy_of(p))
                if o and o["direction"] and o["direction"] != p["direction"]:
                    self.log(f"{bar_close:%H:%M} {o['label']} now points the other way: exiting its position")
                    with self._on(p):
                        self._exit("opposite_signal")
                    self.strat_block[o["strategy"]] = max(self.strat_block.get(o["strategy"], bar_close),
                                                          bar_close + timedelta(minutes=cfg.timeframe * cfg.bias_cooldown_bars))
        cands = [o for o in opps if o["decision"] == "CANDIDATE"]
        for o in cands:
            o["action"] = {1: "BUY CE / SELL PE", -1: "BUY PE / SELL CE"}[o["direction"]]
        t = bar_close.time()
        if {o["direction"] for o in cands} == {1, -1}:
            for o in cands:
                self._scan_reject(o, bar_close, "strategies disagree on this candle (one says bullish, another bearish): no trade")
            cands = []
        for o in sorted(cands, key=scanner.rank_key):
            k, d = o["strategy"], o["direction"]
            floor = cfg.scan_min_quality
            why = None
            if self.paused:
                why = "automation is paused (no new entries)"
            elif not (_hm(cfg.entry_start) <= t <= _hm(cfg.cutoff)) or t >= st.SQUARE_OFF:
                why = f"outside the entry window {cfg.entry_start}-{cfg.cutoff}"
            elif not cfg.scan_allow_unvalidated and not o["evidence"]["status"] == "positive":
                why = (f"{o['label']} has a {o['evidence']['label']} ({o['evidence']['note']}); it trades only when you allow strategies "
                       f"without a validated positive result")
            elif cfg.max_trades_per_day and self.trades_today >= cfg.max_trades_per_day:
                why = f"daily trade limit ({cfg.max_trades_per_day}) reached"
            elif self.strat_block.get(k) and bar_close <= self.strat_block[k]:
                why = f"this strategy's last exit (or cool-down) closes this candle to it until {self.strat_block[k]:%H:%M}"
            elif k in self.strat_entry and pd.Timestamp(self.strat_entry[k]) >= pd.Timestamp(o["episode_start"]):
                why = f"this signal (running since {pd.Timestamp(o['episode_start']):%H:%M}) was already traded: waiting for a new one"
            elif any(p["direction"] != d for p in self.book):
                other = next(self._strategy_of(p) for p in self.book if p["direction"] != d)
                why = f"opposite to the open position of {other} (no hedging against another strategy)"
            elif o["quality"] + scanner.LATE_MAX < floor:
                why = f"quality {o['quality']:g} of 100 cannot reach the minimum {floor:g} even with a perfect contract"
            if why:
                self._scan_reject(o, bar_close, why)
                continue
            pick = self._bias_pick(d)
            if pick is None:
                self._scan_reject(o, bar_close, f"{'CE' if d > 0 else 'PE'} trades are not enabled in your settings")
                continue
            mode, side, typ = pick
            o["action"] = f"{side} {typ}"
            analysis = {**expl, "strategy": k, "signal": "BUY CE" if d > 0 else "BUY PE", "direction": d, "instrument": f"{side} {typ}",
                        "summary": f"SCANNER: {o['label']} {side} {typ} candidate, candle quality {o['quality']:g} of 100",
                        "quality": {"total": o["quality"], "min": floor, "final": False, "components": o["components"]},
                        "scanner": {"strategy": k, "episode_start": o["episode_start"], "evidence": o["evidence"], "rank_quality": o["quality"]}}
            leg = st.Leg(day=self.day, direction=d, entry_ts=bar_close, signal_close=float(r["close"]),
                         signal_bar_start=pd.Timestamp(r["start"]).to_pydatetime(), ordinal=self.trades_today + 1,
                         extra={"strategy_keys": [k]})
            n_before, seen = self.trades_today, len(self.scan_rejected)
            self._try_entry(now, leg, refs={"exec_mode": mode, "action": f"{side} {typ}", "confidence": o["quality"], "analysis": analysis})
            if self.trades_today > n_before:
                o["decision"] = "ENTER"
                self.strat_entry[k] = bar_close
                o["reasons"] = [f"entered {side} {typ}"]
            else:
                o["decision"] = "REJECTED"
                o["reasons"] = [self.scan_rejected[0]["reason"] if len(self.scan_rejected) > seen else "no order was placed (see the log)"]
        self.scan_state = {
            "bar_close": pd.Timestamp(bar_close).isoformat(), "scanned_at": now.isoformat(), "min_quality": cfg.scan_min_quality,
            "decision": "BUY" if any(o["decision"] == "ENTER" for o in opps) else "HOLD",
            "opportunities": [{**o, "components": o["components"]} for o in opps],
            "open_positions": len(self.book), "max_open_positions": self._slots()}
        taken = [o for o in opps if o["decision"] == "ENTER"]
        self.log(f"{bar_close:%H:%M} scanner: {len([o for o in opps if o['state'] == 'signal'])} signal(s), {len(taken)} entered"
                 + ("" if taken else " (HOLD)"))

    def _scan_finalize(self, c, side: str, refs: dict, key: str | None) -> str | None:
        """Scanner only, once the contract passed its checks: add the liquidity, Greeks and reward/risk components to the candle score
        and refuse the order when the total is below the minimum. Returns the reason to refuse, or None."""
        cfg = self.cfg
        a = refs.get("analysis") or {}
        q = a.get("quality") or {}
        comps = list(q.get("components") or [])
        comps += scanner.contract_components(a.get("contract_checks") or [], side)
        prem = float(a.get("entry_premium_seen") or 0)
        lv = stops.stop_levels(cfg, side, prem, self.last_atr, lambda: self.market.option_delta(c)) if prem else None
        if lv is not None and lv.error and not lv.invalid:
            lv = stops.stop_levels(dc_replace(cfg, stop_mode="pct"), side, prem, self.last_atr, lambda: None)
        rr, note = scanner.reward_risk(side, prem, getattr(lv, "stop", None), getattr(lv, "target", None), c.lot_size, self.cost_cfg)
        comps.append(scanner.reward_risk_component(rr, note))
        total = scanner.total(comps)
        a["quality"] = {"total": total, "min": cfg.scan_min_quality, "final": True, "components": comps,
                        "note": "a count of sound conditions met, not a probability of winning"}
        refs["analysis"] = a
        refs["confidence"] = total
        if total < cfg.scan_min_quality:
            low = [f"{x['label']} {x['points']:g}/{x['max']:g}" for x in comps if x["points"] < x["max"] / 2]
            return f"quality {total:g} of 100 is below the minimum {cfg.scan_min_quality:g} (weak: {', '.join(low) or 'none'})"
        if rr is not None and rr <= 0:
            return f"the target does not cover the costs ({note})"
        return None

    def _bias_pick(self, d: int) -> tuple[str, str, str] | None:
        """(execution mode, BUY/SELL, CE/PE) for a direction, from the instruments you enabled. Buying is
        preferred; writing (selling the opposite option) is used only when buying that side is switched off."""
        allow = set(self.cfg.bias_allow)
        for side, typ in ((("BUY", "CE"), ("SELL", "PE")) if d > 0 else (("BUY", "PE"), ("SELL", "CE"))):
            if f"{side}_{typ}" in allow:
                buy_mode = self.cfg.exec_mode if self.cfg.exec_mode in ("ITM5_BUY", "ATM_BUY") else "ATM_BUY"
                return ("ATM_SELL" if side == "SELL" else buy_mode), side, typ
        return None

    def _bias_contract_check(self, c, side: str, refs: dict | None) -> str | None:
        """Premium, open interest, spread and delta checks. A value Groww or the stored data does not give is
        recorded as 'not available' and not checked. Returns the reason to refuse, or None."""
        cfg, checks = self.cfg, []

        def add(name, ok, text_):
            checks.append({"check": name, "ok": ok, "text": text_})
        try:
            prem = float(self.market.option_ltp(c))
        except Exception as exc:
            return f"the option premium is unavailable ({exc})"
        ok = prem >= cfg.min_premium
        add("premium", ok, f"premium {prem:.2f} {'≥' if ok else '<'} the minimum {cfg.min_premium:g}")
        if cfg.entry_strategy == "scored" and prem > 0:
            # option premium validation of the ATR stop, before anything is opened and the same in paper and replay: the stop the
            # engine would use (the percentage stop when no delta is known, as replay does) must be a controlled, meaningful distance
            lv = stops.stop_levels(cfg, side, prem, self.last_atr, lambda: self.market.option_delta(c))
            if lv.error and not lv.invalid:
                lv = stops.stop_levels(dc_replace(cfg, stop_mode="pct"), side, prem, self.last_atr, lambda: None)
            if lv.invalid:
                add("stop", False, lv.error)
            elif lv.stop is not None:
                add("stop", True, f"stop {lv.stop:.2f} is {100 * abs(prem - lv.stop) / prem:.1f}% of the premium "
                                  f"(allowed {cfg.sc_stop_min_pct:g}% to {cfg.sc_stop_max_pct:g}%)")
        add("expiry", True, f"expiry {c.expiry:%d %b %Y} ({(c.expiry - self.day).days} day(s) away), lot size {c.lot_size}")
        try:
            q = self.market.option_quote(c) if hasattr(self.market, "option_quote") else {}
        except Exception:
            q = {}
        oi, bid, ask, delta = q.get("oi"), q.get("bid"), q.get("ask"), q.get("delta")
        if cfg.min_oi > 0:
            if oi is None:
                add("open_interest", None, "open interest not available: not checked")
            else:
                add("open_interest", oi >= cfg.min_oi,
                    f"open interest {oi:,.0f} {'≥' if oi >= cfg.min_oi else '<'} the minimum {cfg.min_oi:,.0f}")
        elif oi is not None:
            add("open_interest", True, f"open interest {oi:,.0f}")
        if cfg.max_spread_pct > 0:
            if bid and ask and bid > 0 and ask >= bid:
                sp = (ask - bid) / ((ask + bid) / 2) * 100
                add("spread", sp <= cfg.max_spread_pct,
                    f"bid {bid:.2f} / ask {ask:.2f}: spread {sp:.1f}% {'≤' if sp <= cfg.max_spread_pct else '>'} {cfg.max_spread_pct:g}%")
            else:
                add("spread", None, "bid/ask not available: spread not checked")
        if delta is None:
            add("delta", None, "delta not available: not checked")
        elif side == "BUY" and cfg.min_delta > 0:
            ok = abs(delta) >= cfg.min_delta
            add("delta", ok, f"|delta| {abs(delta):.2f} {'≥' if ok else '<'} the minimum {cfg.min_delta:g} for a bought option")
        elif side == "SELL":
            ok = abs(delta) <= SELL_MAX_DELTA
            add("delta", ok, f"|delta| {abs(delta):.2f} {'≤' if ok else '>'} {SELL_MAX_DELTA:g} for a written option")
        if refs is not None and isinstance(refs.get("analysis"), dict):
            refs["analysis"] = {**refs["analysis"], "contract_checks": checks, "entry_premium_seen": round(prem, 2)}
        failed = [x["text"] for x in checks if x["ok"] is False]
        return "; ".join(failed) if failed else None

    def _bias_levels_from_fill(self, p: dict) -> None:
        """Replay has no paper risk calculation: set stop and target from the fill (percentage stop when no delta)."""
        cfg, c = self.cfg, p["contract"]
        lv = stops.stop_levels(cfg, p["side"], float(p["entry_price"]), self.last_atr, lambda: self.market.option_delta(c))
        if lv.error:
            lv = stops.stop_levels(dc_replace(cfg, stop_mode="pct"), p["side"], float(p["entry_price"]), self.last_atr,
                                   lambda: None)
        if lv.stop is None:      # the position is already open: never leave it without a stop (the range check ran before the entry)
            lv = stops.stop_levels(dc_replace(cfg, stop_mode="pct", entry_strategy="bias"), p["side"], float(p["entry_price"]), self.last_atr,
                                   lambda: None)
        p.update(stop_premium=lv.stop, target_premium=lv.target, levels_set=True)
        self._update_trade(p["id"], {"stop_premium": lv.stop, "target_premium": lv.target})
        self.log(f"Levels from the fill {p['entry_price']:.2f}: stop {lv.stop}, target {lv.target} ({lv.how})")

    def _bias_exits(self, now: datetime) -> None:
        """Time exit, trailing stop, target and (replay) stop. The paper stop-loss itself is _premium_stop."""
        p, cfg = self.position, self.cfg
        if not p or p.get("exiting") or self.state == "error":
            return
        buy = p["side"] == "BUY"
        entered = pd.Timestamp(p["entry_ts"]).to_pydatetime().replace(tzinfo=None)
        if cfg.bias_max_hold_min and (now - entered).total_seconds() >= cfg.bias_max_hold_min * 60:
            self.log(f"Held {cfg.bias_max_hold_min} min: time exit")
            self._exit("time_exit")
            return
        sym = p["contract"].trading_symbol
        ltp, at = self.last_ltp.get(sym), self.last_ltp_at.get(sym)
        if ltp is None or at is None or (self.market.now() - at).total_seconds() > STALE_PRICE_SEC:
            return
        if not self.paper and p.get("stop_premium") is None and not p.get("levels_set"):
            self._bias_levels_from_fill(p)
        if cfg.profit_target_net > 0:
            # net of slippage, brokerage, STT and the other charges, valued at the current premium (the exit fill)
            net = self._pnl(p, ltp)["net"]
            if net >= cfg.profit_target_net:
                self.log(f"Net profit {net:+,.2f} reached the ₹{cfg.profit_target_net:,.0f} target (premium {ltp:.2f}): exiting")
                self._exit("profit_target")
                return
        entry = float(p["entry_price"])
        best = p["best"] = (max if buy else min)(p.get("best", entry), ltp)
        move_pct = (best - entry) / entry * 100 * (1 if buy else -1)
        if cfg.trail_pct > 0 and p.get("stop_premium") is not None and move_pct >= cfg.trail_activate_pct:
            raw = best * (1 - cfg.trail_pct / 100) if buy else best * (1 + cfg.trail_pct / 100)
            new = costs._round_tick_down(raw) if buy else costs._round_tick_up(raw)
            old = p["stop_premium"]
            if ((new > old) if buy else (new < old)) and ((new < ltp) if buy else (new > ltp)):
                p["stop_premium"] = new
                self._update_trade(p["id"], {"stop_premium": new})
                loss = lambda s: sizing._loss_at(p["side"], entry, s, p["qty"], self.cost_cfg, True)["loss"]
                self._record_stop(p["id"], old, new, loss(old), loss(new), "trail",
                                  f"trailing {cfg.trail_pct:g}% from the best premium {best:.2f}")
                self.log(f"Trailing stop-loss {old:.2f} → {new:.2f} (best premium {best:.2f})")
        stop = p.get("stop_premium")
        if not self.paper and stop is not None and ((ltp <= stop) if buy else (ltp >= stop)):
            self.log(f"Premium {ltp:.2f} reached the stop-loss {stop:.2f}: exiting", "warn")
            self._exit("stop_loss")
            return
        tgt = p.get("target_premium")
        if tgt is not None and ((ltp >= tgt) if buy else (ltp <= tgt)):
            self.log(f"Premium {ltp:.2f} reached the target {tgt:.2f}: exiting")
            self._exit("target")

    def _exit_detail(self, p: dict, reason: str, price: float) -> dict:
        if self.cfg.signal_mode != "bias":
            return {}
        b = self.bias_state or {}
        return {"exit_detail": json.dumps({
            "reason": reason, "exit_premium": round(float(price), 2), "best_premium": p.get("best"),
            "stop_at_exit": p.get("stop_premium"), "target": p.get("target_premium"),
            "bias_at_exit": {k: b.get(k) for k in ("bar_close", "bias", "confidence", "signal", "trend_5m", "trend_15m")},
        }, default=str)}

    # ------------------------------------------------------------ settings and targets changed while running
    LIVE_TUNABLE = frozenset({
        "bias_indicators", "bias_confirm_tf", "bias_min_confidence", "bias_trend_thr", "bias_confirm_thr", "bias_min_atr_pct", "bias_allow",
        "bias_exit_opposite", "bias_max_hold_min", "bias_cooldown_bars", "target_rr", "trail_pct", "trail_activate_pct",
        "sell_risk_pct", "min_premium", "min_oi", "max_spread_pct", "min_delta", "risk_pct", "daily_risk_pct",
        "max_daily_loss", "max_trades_per_day", "max_lots", "min_balance", "stop_mode", "stop_atr", "stop_pct",
        "stop_points", "entry_start", "cutoff", "exec_mode", "lots", "premarket_mode", "profit_target_net",
        "entry_strategy", "cf_factors", "cf_require", "cf_min_score", "cf_adr_filter", "cf_adr_period", "cf_adr_max_used",
        "cf_fvg_min_atr", "cf_fvg_max_age", "cf_htf", "sc_min_score", "sc_adr_period", "sc_adr_max_used", "sc_fvg_min_atr",
        "sc_fvg_max_age", "sc_ctx_tf", "sc_stop_min_pct", "sc_stop_max_pct", "max_open_positions", "max_open_risk_pct",
        "max_strategy_positions", "max_strategy_risk_pct", "scan_min_quality", "scan_allow_unvalidated"})

    def update_settings(self, changes: dict) -> dict:
        """Apply new bias-mode settings to the running engine (no restart). The whole new configuration is validated
        first; a bad value changes nothing. The next candle's analysis and the next entry use the new values."""
        with self._lock:
            if self.cfg.signal_mode != "bias":
                raise ValueError("Settings can be changed while running for the automated bias engine only.")
            bad = sorted(set(changes) - self.LIVE_TUNABLE)
            if bad:
                raise ValueError(f"These settings cannot be changed while running: {', '.join(bad)}")
            new = dc_replace(self.cfg, **changes).validate()
            old, self.cfg = self.cfg, new
            self._limit_day = None
            diff = [f"{k}: {getattr(old, k)} → {getattr(new, k)}" for k in changes if getattr(old, k) != getattr(new, k)]
            self.log("Settings changed: " + ("; ".join(diff) if diff else "no change"))
            try:
                with self.dbe.begin() as c:
                    c.execute(text("UPDATE live_sessions SET config=CAST(:c AS JSONB) WHERE id=:i"),
                              {"c": json.dumps(asdict(new)), "i": self.session_id})
            except Exception:
                pass
            return {"changed": diff}

    def set_paper_target(self, new_target: float) -> dict:
        """Change the open paper position's target premium (it must be on the profit side of the current premium)."""
        with self._lock:
            p = self.position
            if not self.paper or not p:
                raise ValueError("No open paper position.")
            sym = p["contract"].trading_symbol
            try:
                ltp = float(self.market.option_ltp(p["contract"]))
                self.last_ltp[sym], self.last_ltp_at[sym] = ltp, self.market.now()
            except Exception as exc:
                raise ValueError(f"Current premium unavailable ({exc}); the target was not changed.")
            new_target = (costs._round_tick_up(float(new_target)) if p["side"] == "BUY"
                          else costs._round_tick_down(float(new_target)))
            if new_target <= 0:
                raise ValueError("The target must be above zero.")
            if p["side"] == "BUY" and new_target <= ltp:
                raise ValueError(f"The target {new_target:.2f} must be above the current premium {ltp:.2f}.")
            if p["side"] == "SELL" and new_target >= ltp:
                raise ValueError(f"The target {new_target:.2f} must be below the current premium {ltp:.2f}.")
            old = p.get("target_premium")
            p["target_premium"] = new_target
            self._update_trade(p["id"], {"target_premium": new_target})
            self.log(f"Target changed {'none' if old is None else f'{old:.2f}'} → {new_target:.2f}")
            return {"trade_id": p["id"], "old_target": old, "new_target": new_target, "ltp": ltp}

    # ------------------------------------------------------------ editing the paper stop-loss
    def _record_stop(self, tid, old, new, old_loss, new_loss, source, note=None):
        try:
            with self.dbe.begin() as c:
                c.execute(text("INSERT INTO paper_stop_changes (trade_id, ts, old_stop, new_stop, old_max_loss, "
                               "new_max_loss, source, note) VALUES (:t, :ts, :o, :n, :ol, :nl, :s, :note)"),
                          {"t": tid, "ts": self.market.now(), "o": old, "n": new, "ol": old_loss, "nl": new_loss,
                           "s": source, "note": note})
        except Exception as exc:
            log.warning("stop change not recorded: %s", exc)

    def set_paper_stop(self, new_stop: float) -> dict:
        """Change the open paper position's stop-loss. Refused, with the reason, if it would exceed the
        trade's risk amount or today's remaining loss limit, or sit on the wrong side of the current premium."""
        with self._lock:
            p = self.position
            if not self.paper:
                raise ValueError("Stop-loss editing is for paper positions only.")
            if not p or p.get("stop_premium") is None:
                raise ValueError("No open paper position with a stop-loss.")
            new_stop = costs._round_tick_down(float(new_stop)) if p["side"] == "BUY" else costs._round_tick_up(float(new_stop))
            sym = p["contract"].trading_symbol
            try:
                ltp = float(self.market.option_ltp(p["contract"]))
                self.last_ltp[sym], self.last_ltp_at[sym] = ltp, self.market.now()
            except Exception as exc:
                raise ValueError(f"Current premium unavailable ({exc}). The stop could not be checked, so it was not changed.")
            if new_stop <= 0:
                raise ValueError("The stop-loss must be above zero.")
            if p["side"] == "BUY" and new_stop >= ltp:
                raise ValueError(f"The stop {new_stop:.2f} must be below the current premium {ltp:.2f}.")
            if p["side"] == "SELL" and new_stop <= ltp:
                raise ValueError(f"The stop {new_stop:.2f} must be above the current premium {ltp:.2f}.")
            risk = p.get("risk") or {}
            old_loss = float(risk.get("max_loss") or 0.0)
            new_loss = sizing._loss_at(p["side"], p["entry_price"], new_stop, p["qty"], self.cost_cfg, True)["loss"]
            budget = float(risk.get("risk_amount") or 0.0)
            acct = paper_account.state(self.day, self.cfg, None, None, eng=self.dbe)
            day_room = None if acct["daily_limit"] is None else max(0.0, acct["daily_limit"] + min(0.0, acct["realised_today"]))
            if new_loss > old_loss:
                if budget and new_loss > budget:
                    raise ValueError(f"Refused: the new maximum loss ₹{new_loss:,.0f} exceeds this trade's risk amount "
                                     f"₹{budget:,.0f} ({risk.get('risk_pct')}% of ₹{risk.get('capital', 0):,.0f}).")
                if day_room is not None and new_loss > day_room:
                    raise ValueError(f"Refused: the new maximum loss ₹{new_loss:,.0f} exceeds the ₹{day_room:,.0f} left "
                                     f"in today's loss limit.")
            old = p["stop_premium"]
            p["stop_premium"] = new_stop
            tgt = p.get("target_premium")
            p["risk"] = {**risk, "max_loss": new_loss, "stop": new_stop,
                         "risk_reward": round(abs(tgt - p["entry_price"]) / abs(p["entry_price"] - new_stop), 2)
                         if tgt and p["entry_price"] != new_stop else None}
            self._update_trade(p["id"], {"stop_premium": new_stop})
            self._record_stop(p["id"], old, new_stop, old_loss, new_loss, "user")
            self.log(f"Stop-loss changed {old:.2f} → {new_stop:.2f}: maximum loss ₹{old_loss:,.0f} → ₹{new_loss:,.0f}")
            return {"trade_id": p["id"], "old_stop": old, "new_stop": new_stop, "old_max_loss": old_loss,
                    "new_max_loss": new_loss, "ltp": ltp}

    # ------------------------------------------------------------ manual confirmation (live mode)
    def _propose(self, now: datetime, leg, c, side, qty, strike, typ, expiry, refs):
        """Hold a live entry order until the user confirms it; it lapses with the signal."""
        import uuid
        dirn = "Bullish" if leg.direction > 0 else "Bearish"
        try:
            ltp = round(float(self.market.option_ltp(c)), 2)
        except Exception:
            ltp = None
        self.pending = {"id": uuid.uuid4().hex[:10], "leg": leg, "contract": c, "side": side, "qty": qty,
                        "strike": strike, "typ": typ, "expiry": expiry, "refs": refs, "ltp": ltp, "created": now,
                        "expires": leg.entry_ts + timedelta(seconds=self.cfg.stale_entry_sec)}
        self.log(f"{dirn} signal (bar closed {leg.entry_ts:%H:%M}): {side} {c.trading_symbol} x{qty} is waiting for "
                 f"your confirmation until {self.pending['expires']:%H:%M:%S}")
        r = refs or {}
        self._alert(f"{side} {typ}", leg.entry_ts, direction=dirn, nifty=round(leg.signal_close, 2), strike=strike,
                    opt_type=typ, symbol=c.trading_symbol, expiry=expiry.isoformat(), qty=qty, entry_price=ltp,
                    status="awaiting your confirmation", stop=r.get("stop_ref"), target=r.get("target_ref"),
                    score=r.get("score"))

    def confirm_pending(self, pid: str) -> None:
        with self._lock:
            p = self.pending
            if not p or p["id"] != pid:
                raise ValueError("That order is no longer waiting for confirmation.")
            now = self.market.now()
            if now > p["expires"]:
                self.pending = None
                raise ValueError("The signal expired before you confirmed: no order was placed.")
            if self.state in ("halted", "error") or self.position:
                self.pending = None
                raise ValueError("The engine can't enter now (halted, error or a position is open). No order placed.")
            self.pending = None
            self.log(f"You confirmed {p['side']} {p['contract'].trading_symbol} x{p['qty']}")
            self._execute_entry(p["leg"], p["contract"], p["side"], p["qty"], p["strike"], p["typ"], p["expiry"], p["refs"])

    def reject_pending(self, pid: str) -> None:
        with self._lock:
            if self.pending and self.pending["id"] == pid:
                self.log(f"You rejected {self.pending['side']} {self.pending['contract'].trading_symbol}: no order placed")
                self.pending = None

    def _execute_entry(self, leg, c, side, qty, strike, typ, expiry, refs=None):
        dirn = "Bullish" if leg.direction > 0 else "Bearish"
        self.log(f"{dirn} crossover (bar closed {leg.entry_ts:%H:%M}, NIFTY {leg.signal_close:.2f}) → "
                 f"{side} {c.trading_symbol} x{qty}")
        try:
            fill = self.broker.execute(c, side, qty, f"E{leg.entry_ts:%H%M}{self.day:%d%m}{c.trading_symbol[-9:]}{side[0]}")
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
            "entry_order_id": fill["order_id"], "status": "OPEN", "signal_mode": self.cfg.signal_mode,
            **({"strategy": self.cfg.strategy, "scalp_config": self.cfg.scalp_config or None} if self.cfg.signal_mode == "scalp" else {}),
            **(refs or {})})
        self.position = {"id": tid, "direction": leg.direction, "side": side, "contract": c, "qty": qty,
                         "entry_price": fill["price"], "entry_ts": fill["ts"], "signal_ts": leg.entry_ts,
                         "entry_ref": leg.signal_close, **(refs or {})}
        self.trades_today += 1
        self.log(f"ENTERED {side} {c.trading_symbol} x{qty} @ {fill['price']:.2f} ({fill['order_id']})")
        if self.paper and (refs or {}).get("stop_premium") is not None:
            self._record_stop(tid, None, refs["stop_premium"], None, refs["risk"].get("max_loss"), "entry",
                              refs["risk"].get("stop_method"))
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
                                     "charges": json.dumps(pnl["charges"]), "net": pnl["net"], "status": "CLOSED",
                                     **self._exit_detail(p, reason, fill["price"])})
        self.realised_today += pnl["net"]
        self._alert("SELL" if p["side"] == "BUY" else "BUY BACK", p.get("signal_ts") or p["entry_ts"],
                    symbol=p["contract"].trading_symbol, opt_type=p["contract"].opt_type, strike=p["contract"].strike,
                    entry_price=round(p["entry_price"], 2), exit_price=round(fill["price"], 2), reason=reason,
                    net=pnl["net"], exit_ts=pd.Timestamp(fill["ts"]).isoformat())
        self.position = None
        self.exit_failures = 0
        self.log(f"EXITED {p['contract'].trading_symbol} @ {fill['price']:.2f} ({reason}) · net {pnl['net']:+,.2f}")
        if self.cfg.signal_mode == "bias":
            # Never re-enter on the candle that exited: the next entry needs a candle that opened after this exit.
            closed_at = self._candle_close_after(pd.Timestamp(fill["ts"]).to_pydatetime().replace(tzinfo=None))
            if self.cfg.entry_strategy == "scanner":
                if self._strategy_of(p) and closed_at:
                    self.strat_block[self._strategy_of(p)] = closed_at     # only the strategy that exited waits; the others are independent
            else:
                self._no_entry_through = closed_at
            if reason == "profit_target":
                self.target_hits_today += 1
                if self.cfg.profit_target_net > 0:
                    self._last_entry_signal = None      # a net profit-target exit releases the signal: the next candle may re-enter
                self.log(f"Profit target hit: net {pnl['net']:+,.2f} (target ₹{self.cfg.profit_target_net:,.0f}). "
                         f"Next entry: a new analysis on a candle closing after {closed_at:%H:%M}"
                         if closed_at else f"Profit target hit: net {pnl['net']:+,.2f}")

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
        """Open P&L (net of charges) of every open position, None when any price is unavailable."""
        total = 0.0
        for p in self.book:
            try:
                ltp = self.market.option_ltp(p["contract"])
            except Exception:
                return None
            self.last_ltp[p["contract"].trading_symbol] = ltp
            self.last_ltp_at[p["contract"].trading_symbol] = self.market.now()
            total += self._pnl(p, ltp)["net"]
        return total

    def _book_mtm(self) -> float | None:
        """Open P&L from the latest prices already read (no network call), for the capital figures."""
        if not self.book:
            return None
        tot = 0.0
        for p in self.book:
            ltp = self.last_ltp.get(p["contract"].trading_symbol)
            tot += self._pnl(p, ltp)["net"] if ltp else 0.0
        return tot

    def _daily_limit(self) -> float:
        """₹ daily loss limit. Paper: the smaller of max_daily_loss and daily_risk_pct of the day's starting capital."""
        if not self.paper:
            return self.cfg.max_daily_loss
        if self._limit_day != self.day:
            st_ = paper_account.state(self.day, self.cfg, eng=self.dbe)
            self._limit_day, self._limit_val = self.day, st_["daily_limit"] or 0.0
        return self._limit_val

    def _risk_check(self, now: datetime):
        m = self.mtm() if self.book else 0.0      # also refreshes LTP for the UI
        limit = self._daily_limit()
        if m is None or not limit or self.state in ("halted", "error"):
            return
        total = self.realised_today + m
        if total <= -abs(limit):
            self.log(f"Daily loss limit hit ({total:,.2f} ≤ -{limit:,.0f}): squaring off", "warn")
            for p in list(self.book):
                with self._on(p):
                    self._exit("daily_loss_limit")
            self._halt("Daily loss limit reached: no more trades today")

    def _halt(self, reason: str, error: bool = False):
        self.state = "error" if error else "halted"
        self.halt_reason = reason
        self.log(reason, "error" if error else "warn")

    # ------------------------------------------------------------ status for UI
    def _automation(self, nxt: datetime | None) -> dict:
        """What the continuous paper automation is doing right now, in plain words (bias mode, caller holds the lock)."""
        cfg, now = self.cfg, self.market.now()
        later = next((c for c in self._bar_closes(self.day) if self._no_entry_through and c > self._no_entry_through), None) if self.day else None
        if self.state in ("halted", "error"):
            phase, detail = "halted", self.halt_reason or "The engine is halted: no new entries."
        elif self.book and cfg.entry_strategy == "scanner":
            n = len(self.book)
            if any(p.get("xf") or p.get("pending_reason") or p.get("exiting") for p in self.book):
                phase, detail = "exiting", "Closing a position; an exit is being retried or confirmed."
            elif self.paused:
                phase, detail = "paused", f"Paused: {n} open position(s) are managed, no new entry is taken."
            elif n >= self._slots():
                phase, detail = "holding", f"Holding {n} open paper position(s), the maximum of {self._slots()}: no new entry until one closes."
            else:
                phase = "scanning"
                detail = (f"Holding {n} open paper position(s) and scanning every closed {cfg.timeframe}-minute candle for new qualified signals "
                          f"(room for {self._slots() - n} more).")
        elif self.position:
            p = self.position
            if self.exit_failures or p.get("pending_reason") or p.get("exiting"):
                phase, detail = "exiting", "Closing the position; an exit is being retried or confirmed."
            else:
                phase = "holding"
                tgt = f" until the net profit reaches ₹{cfg.profit_target_net:,.0f}" if cfg.profit_target_net > 0 else ""
                detail = f"Holding the open paper position{tgt}, the stop-loss or the 15:00 square-off."
        elif self.paused:
            phase, detail = "paused", "Paused: the analysis keeps running but no new entry is taken."
        elif now.weekday() >= 5 or now.time() < MARKET_OPEN or now.time() >= MARKET_CLOSE:
            phase, detail = "waiting", "Market closed: waiting for the next session."
        elif cfg.max_trades_per_day and self.trades_today >= cfg.max_trades_per_day:
            phase, detail = "limit", f"Daily trade limit ({cfg.max_trades_per_day}) reached: no new entries today."
        elif not (_hm(cfg.entry_start) <= now.time() <= _hm(cfg.cutoff)):
            phase, detail = "waiting", f"Outside the entry window {cfg.entry_start}-{cfg.cutoff}: no new entries."
        elif cfg.entry_strategy != "scanner" and self._no_entry_through and nxt is not None and nxt <= self._no_entry_through:
            phase = "waiting"
            detail = (f"Waiting for a new candle after the last exit (the {self._no_entry_through:%H:%M} candle contains it); "
                      f"earliest next entry on the {later:%H:%M} candle." if later else "No further candle today.")
        elif cfg.entry_strategy != "scanner" and self._cooldown_until and nxt is not None and nxt < self._cooldown_until:
            phase, detail = "waiting", f"Cooling down after an opposite-signal exit until {self._cooldown_until:%H:%M}."
        else:
            phase = "ready"
            need = (f"a strategy that is ON in Trading Settings signals with a quality score of at least {cfg.scan_min_quality:g} of 100" if cfg.entry_strategy == "scanner" else
                    "a strategy that is ON in Trading Settings signals" if cfg.entry_strategy == "configured" else
                    f"the confluence confirmation score is at least {cfg.cf_min_score:g}%" if cfg.entry_strategy == "confluence"
                    else f"the strategy score is at least {cfg.sc_min_score:g} of 100 and every gate is met" if cfg.entry_strategy == "scored"
                    else f"the bias confidence is at least {cfg.bias_min_confidence:g}%")
            detail = (f"Next analysis at {nxt:%H:%M}: enters if {need} and a valid, new signal exists." if nxt else "No further candle today.")
        labels = {"halted": "Halted", "exiting": "Exiting", "holding": "Holding a position", "paused": "Paused", "scanning": "Scanning (positions open)",
                  "limit": "Daily limit reached", "waiting": "Waiting",
                  "ready": "Ready for re-entry" if self.trades_today else "Ready for entry"}
        return {"phase": phase, "label": labels[phase], "detail": detail, "paused": self.paused,
                "min_confidence": {"confluence": cfg.cf_min_score, "scored": cfg.sc_min_score}.get(cfg.entry_strategy, cfg.bias_min_confidence),
                "strategy": cfg.entry_strategy, "profit_target_net": cfg.profit_target_net,
                "target_hits": self.target_hits_today, "trades_today": self.trades_today, "open_positions": len(self.book),
                "max_open_positions": self._slots(), "trade_cap": cfg.max_trades_per_day or None,
                "no_entry_through": self._no_entry_through.isoformat() if self._no_entry_through else None}

    def status(self) -> dict:
        with self._lock:
            def view(p: dict) -> dict:
                c = p["contract"]
                ltp = self.last_ltp.get(c.trading_symbol)
                a = p.get("analysis") or {}
                return {"id": p.get("id"), "trading_symbol": c.trading_symbol, "side": p["side"],
                        "direction": "Bullish" if p["direction"] > 0 else "Bearish",
                        "qty": p["qty"], "strike": c.strike, "opt_type": c.opt_type, "expiry": c.expiry.isoformat(),
                        "entry_price": p["entry_price"], "entry_ts": pd.Timestamp(p["entry_ts"]).isoformat(),
                        "ltp": ltp, "mtm": self._pnl(p, ltp)["net"] if ltp else None,
                        "exit_failures": int(p.get("xf", 0)), "score": p.get("score"),
                        "entry_reason": a.get("summary"), "entry_confidence": p.get("confidence"),
                        "action": p.get("action"), "strategy": self._strategy_of(p),
                        "quality": (a.get("quality") or {}).get("total"),
                        "risk_amount": (p.get("risk") or {}).get("max_loss"),
                        "stop_ref": p.get("stop_ref"), "target_ref": p.get("target_ref"),
                        **stops.position_levels(p)}
            pos = view(self.book[0]) if self.book else None
            positions = [view(p) for p in self.book]
            pend = None
            if self.pending:
                q = self.pending
                pend = {"id": q["id"], "side": q["side"], "trading_symbol": q["contract"].trading_symbol,
                        "strike": q["strike"], "opt_type": q["typ"], "expiry": q["expiry"].isoformat(), "qty": q["qty"],
                        "ltp": q["ltp"], "nifty": round(q["leg"].signal_close, 2),
                        "signal_ts": q["leg"].entry_ts.isoformat(), "expires": q["expires"].isoformat(),
                        "stop_ref": (q["refs"] or {}).get("stop_ref"), "target_ref": (q["refs"] or {}).get("target_ref")}
            nxt = self._next_bar_close(self.processed_until) if self.day else None
            return privacy.redact_live_status({
                "state": self.state, "halt_reason": self.halt_reason, "session_id": self.session_id,
                "config": asdict(self.cfg), "now": self.market.now().isoformat(),
                "day": self.day.isoformat() if self.day else None,
                "next_eval": nxt.isoformat() if nxt else None,
                "last_eval": self.last_eval, "position": pos, "positions": positions, "pending_order": pend,
                "settings": {"configured": self.cfg.entry_strategy == "configured", "applied_version": self._settings_version,
                             "saved_version": trading_settings.current().version, "error": self.settings_error},
                "trades_today": self.trades_today, "realised_today": round(self.realised_today, 2),
                "nifty": {"price": self.last_spot["price"], "ts": self.last_spot["ts"].isoformat()} if self.last_spot else None,
                "conn_error": self.conn_error,
                "events": list(self.events)[:120], "bars": self.bars_today,
                **({"bias": {"latest": self.bias_state, "history": list(self.bias_history)[:60],
                             "trades_today": self.trades_today, "max_trades": self.cfg.max_trades_per_day or None,
                             "remaining_trades": max(0, self.cfg.max_trades_per_day - self.trades_today) if self.cfg.max_trades_per_day else None,
                             "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
                             "rejected": list(self.rejected)[:30],
                             **({"scan": {"state": self.scan_state, "rejected": list(self.scan_rejected)[:60], "candles_scanned": self.scan_candles,
                                          "open_risk": round(self._open_risk(), 2), "open_positions": len(self.book),
                                          "max_open_positions": self._slots()}}
                                if self.cfg.entry_strategy == "scanner" else {}),
                             "automation": self._automation(nxt)}}
                   if self.cfg.signal_mode == "bias" else {}),
            })
