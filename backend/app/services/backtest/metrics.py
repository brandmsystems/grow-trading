"""Performance metrics computed from a list of trades (dicts with net/gross)."""
from __future__ import annotations


def compute(trades: list[dict], capital: float = 100_000.0) -> dict:
    n = len(trades)
    nets = [t["net"] for t in trades]
    gross = round(sum(t["gross"] for t in trades), 2)
    friction = round(sum(t["friction"] for t in trades), 2)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]       # breakeven counts as non-win
    sum_w, sum_l = sum(wins), -sum(losses)
    equity, peak, max_dd, max_dd_pct = capital, capital, 0.0, 0.0
    curve = []
    for t in trades:
        equity += t["net"]
        peak = max(peak, equity)
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
        if peak > 0:
            max_dd_pct = max(max_dd_pct, dd / peak * 100)
        curve.append(round(equity, 2))
    avg_w = sum_w / len(wins) if wins else 0.0
    avg_l = sum_l / len(losses) if losses else 0.0
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 2) if n else 0.0,
        "gross_pnl": gross,
        "friction": friction,
        "net_pnl": round(sum(nets), 2),
        # None when there are no losing trades (UI shows "∞" if there are wins, "—" otherwise)
        "profit_factor": round(sum_w / sum_l, 3) if sum_l > 0 else None,
        "payoff_ratio": round(avg_w / avg_l, 3) if avg_l > 0 else None,
        "expectancy": round(sum(nets) / n, 2) if n else 0.0,
        "avg_win": round(avg_w, 2),
        "avg_loss": round(-avg_l, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "equity_curve": curve,
    }
