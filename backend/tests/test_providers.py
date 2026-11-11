from datetime import datetime

from app.services.market_data import providers


def test_parse_candles_epoch_seconds_ist():
    # 2025-03-04 09:15 IST == 03:45 UTC
    ts = int((datetime(2025, 3, 4, 3, 45) - datetime(1970, 1, 1)).total_seconds())
    df = providers.parse_candles({"candles": [[ts, 1, 2, 0.5, 1.5, 100], [ts + 60, 1.5, 2, 1, 1.8, 50, 7]]})
    assert df["ts"].iloc[0] == datetime(2025, 3, 4, 9, 15)
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume", "oi"]
    assert df["oi"].iloc[1] == 7 and df["oi"].iloc[0] == 0


def test_parse_candles_epoch_ms_and_iso_strings():
    ms = (datetime(2025, 3, 4, 3, 46) - datetime(1970, 1, 1)).total_seconds() * 1000
    df = providers.parse_candles({"payload": {"candles": [[ms, 1, 1, 1, 1, 0]]}})
    assert df["ts"].iloc[0] == datetime(2025, 3, 4, 9, 16)
    df = providers.parse_candles({"candles": [["2025-03-04T09:17:00", 1, 1, 1, 1, 0, 0],
                                              ["2025-03-04T09:18:00+05:30", 2, 2, 2, 2, 0, 0],
                                              ["2025-03-04T09:17:00", 1, 1, 1, 1, 0, 0]]})
    assert list(df["ts"]) == [datetime(2025, 3, 4, 9, 17), datetime(2025, 3, 4, 9, 18)]


def test_parse_empty_and_option_symbol_regex():
    assert providers.parse_candles({}).empty
    m = providers.OPT_RE.search("NSE-NIFTY-25Nov25-24050-CE")
    assert m.group(1) == "24050" and m.group(2) == "CE"
