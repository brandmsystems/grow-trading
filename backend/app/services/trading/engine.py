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

from app.utils.timeutil import parse_hm
from app.services.notifications import alerts
from app.services.trading import charges as costs
from app.database import db
from app.services.options import sizing
from app.services.strategy import indicators as ind
from app.services.strategy import signals
from app.services.strategy import strategies
from app.services.trading import paper_account
from app.services.strategy import rules as st
from app.services.market_data.live import Contract
from app.services.trading.brokers import OrderUnknown

log = logging.getLogger("live.engine")

MARKET_OPEN, MARKET_CLOSE = time(9, 15), time(15, 30)
STALE_PRICE_SEC = 15      # an option price older than this never triggers a paper stop-loss


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
    order_confirmation: str = "manual" # live mode: manual = you confirm each entry order; auto = engine places it
    costs: dict = field(default_factory=lambda: costs.DEFAULT_COSTS.to_dict())
    # Paper trading only (live and replay use `lots` and are unaffected):
    risk_pct: float = 1.0              # risk per trade, % of available virtual capital
    daily_risk_pct: float = 3.0        # daily loss limit, % of the day's starting capital (0 = off)
    max_open_positions: int = 1        # the engine holds one position at a time
    max_lots: int = 10                 # cap per trade
    min_balance: float = 0.0           # ₹ that must stay available after an entry
    stop_mode: str = "atr"             # atr: premium - delta x stop_atr x NIFTY ATR | pct: premium x (1 - stop_pct %)
    stop_atr: float = 1.0              #   | points: premium - stop_points (fixed premium distance)
    stop_pct: float = 30.0
    stop_points: float = 20.0

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
        if self.order_confirmation not in ("manual", "auto"):
            raise ValueError("order_confirmation must be manual or auto")
        if self.signal_mode not in ("cross", "prediction"):
            raise ValueError("signal_mode must be cross or prediction")
        if self.strategy not in strategies.STRATEGIES:
            raise ValueError("unknown strategy")
        self.min_score = float(self.min_score)
        if not 0 <= self.min_score <= 100:
            raise ValueError("minimum score must be between 0 and 100")
        self.costs = {**costs.DEFAULT_COSTS.to_dict(), **{k: float(v) for k, v in (self.costs or {}).items()}}
        self.risk_pct, self.daily_risk_pct = float(self.risk_pct), float(self.daily_risk_pct)
        if not 0 < self.risk_pct <= 100:
            raise ValueError("risk per trade must be above 0% and at most 100%")
        if not 0 <= self.daily_risk_pct <= 100:
            raise ValueError("daily risk must be between 0% and 100%")
        self.max_open_positions, self.max_lots = int(self.max_open_positions), int(self.max_lots)
        if self.max_open_positions < 1 or self.max_lots < 1:
            raise ValueError("maximum open positions and maximum lots must be at least 1")
        self.min_balance = float(self.min_balance)
        if self.min_balance < 0:
            raise ValueError("minimum balance can't be negative")
        if self.stop_mode not in ("atr", "pct", "points"):
            raise ValueError("stop_mode must be atr, pct or points")
        self.stop_atr, self.stop_pct, self.stop_points = float(self.stop_atr), float(self.stop_pct), float(self.stop_points)
        if self.stop_atr <= 0 or not 0 < self.stop_pct < 100 or self.stop_points <= 0:
            raise ValueError("stop ATR multiple and stop points must be positive, stop % between 0 and 100")
        return self


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
        self.position: dict | None = None
        self.trades_today = 0
        self.realised_today = 0.0
        self.last_eval: dict | None = None
        self.last_ltp: dict = {}
        self.last_ltp_at: dict = {}               # when each LTP was read (stale prices never trigger a stop)
        self.events: deque = deque(maxlen=300)
        self.exit_failures = 0
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
                "stop_premium": r.get("stop_premium"), "target_premium": r.get("target_premium"), "risk": r.get("risk"),
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

            if self.pending and now > self.pending["expires"]:
                self.log(f"Order {self.pending['side']} {self.pending['contract'].trading_symbol} was not confirmed "
                         f"in time: no order placed", "warn")
                self.pending = None
            if self.position and now.time() >= st.SQUARE_OFF:
                self._exit("square_off")
            if self.position and self.position.get("stop_ref") is not None:
                self._check_refs(now)
            if self.position and self.exit_failures:
                self._exit(self.position.get("pending_reason", "retry"))   # retry a failed exit
            self._risk_check(now)
            self._premium_stop()

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
        if not bars.empty:   # paper stop-loss: NIFTY ATR of the signal timeframe, as the dashboard uses
            atr = ind.atr(bars).iloc[-1]
            self.last_atr = float(atr) if pd.notna(atr) and atr > 0 else None
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
        self._execute_entry(leg, c, side, qty, strike, typ, expiry, refs)

    # ------------------------------------------------------------ paper risk management
    def _paper_stop(self, c, side: str, premium: float) -> tuple[float | None, float | None, str, str | None]:
        """(stop premium, target premium, method text, error). Buys stop below the premium, sells above."""
        sgn = 1 if side == "BUY" else -1
        self._last_delta = None
        if self.cfg.stop_mode == "pct":
            stop = premium * (1 - sgn * self.cfg.stop_pct / 100)
            target = premium * (1 + sgn * 2 * self.cfg.stop_pct / 100)
            how = f"{self.cfg.stop_pct:g}% of the premium (target 2× that distance)"
        elif self.cfg.stop_mode == "points":
            stop = premium - sgn * self.cfg.stop_points
            target = premium + sgn * 2 * self.cfg.stop_points
            how = f"{self.cfg.stop_points:g} premium points (target 2× that distance)"
        else:
            if not self.last_atr:
                return None, None, "", "NIFTY ATR unavailable, so no stop-loss can be calculated."
            try:
                delta = self.market.option_delta(c)
            except Exception as exc:
                return None, None, "", f"Option delta unavailable ({exc}), so no stop-loss can be calculated."
            if not delta:
                return None, None, "", "Option delta unavailable, so no stop-loss can be calculated."
            self._last_delta = abs(delta)
            move = abs(delta) * self.last_atr
            stop = premium - sgn * self.cfg.stop_atr * move
            target = premium + sgn * signals.TARGET_ATR * move
            how = (f"delta {abs(delta):.2f} × {self.cfg.stop_atr:g} × NIFTY ATR {self.last_atr:.2f} "
                   f"(target {signals.TARGET_ATR:g}× ATR)")
        rnd = costs._round_tick_down if side == "BUY" else costs._round_tick_up
        stop = rnd(stop)
        if stop <= 0:
            return None, None, how, "The stop-loss works out at or below zero; no position size can be calculated."
        return stop, round(target, 2), how, None

    def _paper_risk(self, leg, c, side: str) -> dict:
        """Steps 1-10 of the paper risk rules: capital, risk %, premium, stop, risk per lot, lots, then
        the daily-loss, balance, lot and open-position checks. Returns the full calculation."""
        acct = paper_account.state(self.day, self.cfg, eng=self.dbe)
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
            r = sizing.risk_size(side, premium, stop, c.lot_size, acct["available"], self.cfg.risk_pct,
                                 available=acct["available"], max_lots=self.cfg.max_lots,
                                 min_balance=self.cfg.min_balance, target=target, cfg=self.cost_cfg,
                                 include_slippage=True)
        r.update(base, stop_method=how, stop_mode=self.cfg.stop_mode, delta=getattr(self, "_last_delta", None),
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
        problems = []
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
        self.last_ltp_at[p["contract"].trading_symbol] = self.market.now()
        return self._pnl(p, ltp)["net"]

    def _daily_limit(self) -> float:
        """₹ daily loss limit. Paper: the smaller of max_daily_loss and daily_risk_pct of the day's starting capital."""
        if not self.paper:
            return self.cfg.max_daily_loss
        if getattr(self, "_limit_day", None) != self.day:
            st_ = paper_account.state(self.day, self.cfg, eng=self.dbe)
            self._limit_day, self._limit_val = self.day, st_["daily_limit"] or 0.0
        return self._limit_val

    def _risk_check(self, now: datetime):
        m = self.mtm() if self.position else 0.0      # also refreshes LTP for the UI
        limit = self._daily_limit()
        if m is None or not limit or self.state in ("halted", "error"):
            return
        total = self.realised_today + m
        if total <= -abs(limit):
            self.log(f"Daily loss limit hit ({total:,.2f} ≤ -{limit:,.0f}): squaring off", "warn")
            if self.position:
                self._exit("daily_loss_limit")
            self._halt("Daily loss limit reached: no more trades today")

    def _halt(self, reason: str, error: bool = False):
        self.state = "error" if error else "halted"
        self.halt_reason = reason
        self.log(reason, "error" if error else "warn")

    def _paper_levels(self, p: dict) -> dict:
        """Paper stop/target with their risk, and the NIFTY levels they correspond to (for the chart)."""
        if p.get("stop_premium") is None:
            return {}
        r = p.get("risk") or {}
        sgn = 1 if p["side"] == "BUY" else -1
        delta, ref = r.get("delta"), r.get("nifty_ref")
        d = 1 if p["direction"] > 0 else -1

        def to_nifty(prem):
            if not (delta and ref) or prem is None:
                return None
            return round(ref - d * sgn * (p["entry_price"] - prem) / delta, 2)
        cap = r.get("capital") or 0
        ml = r.get("max_loss")
        return {"stop_premium": p["stop_premium"], "target_premium": p.get("target_premium"),
                "max_loss": ml, "max_loss_pct": round(100 * ml / cap, 2) if cap and ml is not None else None,
                "risk_amount": r.get("risk_amount"), "risk_reward": r.get("risk_reward"),
                "nifty_stop": to_nifty(p["stop_premium"]), "nifty_target": to_nifty(p.get("target_premium")),
                "stop_method": r.get("stop_method")}

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
                       "stop_ref": p.get("stop_ref"), "target_ref": p.get("target_ref"),
                       **self._paper_levels(p)}
            pend = None
            if self.pending:
                q = self.pending
                pend = {"id": q["id"], "side": q["side"], "trading_symbol": q["contract"].trading_symbol,
                        "strike": q["strike"], "opt_type": q["typ"], "expiry": q["expiry"].isoformat(), "qty": q["qty"],
                        "ltp": q["ltp"], "nifty": round(q["leg"].signal_close, 2),
                        "signal_ts": q["leg"].entry_ts.isoformat(), "expires": q["expires"].isoformat(),
                        "stop_ref": (q["refs"] or {}).get("stop_ref"), "target_ref": (q["refs"] or {}).get("target_ref")}
            nxt = self._next_bar_close(self.processed_until) if self.day else None
            return {
                "state": self.state, "halt_reason": self.halt_reason, "session_id": self.session_id,
                "config": asdict(self.cfg), "now": self.market.now().isoformat(),
                "day": self.day.isoformat() if self.day else None,
                "next_eval": nxt.isoformat() if nxt else None,
                "last_eval": self.last_eval, "position": pos, "pending_order": pend,
                "trades_today": self.trades_today, "realised_today": round(self.realised_today, 2),
                "nifty": {"price": self.last_spot["price"], "ts": self.last_spot["ts"].isoformat()} if self.last_spot else None,
                "conn_error": self.conn_error,
                "events": list(self.events)[:120], "bars": self.bars_today,
            }
