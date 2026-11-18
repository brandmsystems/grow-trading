"""Engine configuration: every setting of one engine run, and its validation."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.strategy import rules as st
from app.services.strategy import strategies
from app.services.trading import charges as costs
from app.utils.timeutil import parse_hm

_hm = parse_hm


@dataclass
class EngineConfig:
    """Everything one engine run is configured with. `validate()` normalises types and refuses
    combinations the engine must never run (for example scalp mode with real money)."""
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
    signal_mode: str = "cross"         # cross: every crossover | prediction: scored signals only | trend: whenever EMAs agree | scalp
    scalp_exit: str = "time"           # scalp mode: time = exit after hold_min | sl_target = stop/target, at most hold_min
    hold_min: int = 5                  # scalp mode: maximum holding time in minutes
    target_pct: float = 10.0           # scalp mode, sl_target: target = premium x (1 + target_pct %)
    scalp_config: str = ""             # scalp mode: the analyzer configuration key it was started from
    strategy: str = "ema_9_21"         # prediction and scalp modes: whose crosses are used (cross/trend trade EMA 9/21)
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
        """Coerce numeric fields and raise ValueError for any setting outside its allowed range.
        Called before every start, so a bad request can never reach the trading loop."""
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
        if self.signal_mode not in ("cross", "prediction", "trend", "scalp"):
            raise ValueError("signal_mode must be cross, prediction, trend or scalp")
        if self.signal_mode == "scalp":
            if self.trade_mode == "live":
                raise ValueError("Scalping runs in paper mode only; real-money scalping is not enabled.")
            if int(self.timeframe) != 5:
                raise ValueError("Scalping uses 5-minute candles: set the timeframe to 5.")
            if self.scalp_exit not in ("time", "sl_target"):
                raise ValueError("scalp exit must be time or sl_target")
            self.hold_min, self.target_pct = int(self.hold_min), float(self.target_pct)
            if not 1 <= self.hold_min <= 60:
                raise ValueError("holding time must be 1 to 60 minutes")
            if not 0 < self.target_pct <= 500:
                raise ValueError("target % must be above 0")
            if not 0 < float(self.stop_pct) < 100:
                raise ValueError("stop % must be between 0 and 100")
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
