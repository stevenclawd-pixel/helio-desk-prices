"""Shared indicator math for the Helio Desk price feed and backtest."""
import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame, bench: pd.Series | None = None) -> pd.DataFrame:
    """df has Open, High, Low, Close, Volume indexed by date. Returns a copy with indicator columns."""
    d = df.copy()
    c = d["Close"]
    for n in (10, 20, 50, 150, 200):
        d[f"sma{n}"] = c.rolling(n).mean()
    d["sma200_slope20"] = d["sma200"] - d["sma200"].shift(20)
    d["hi52"] = d["High"].rolling(252, min_periods=120).max()
    d["lo52"] = d["Low"].rolling(252, min_periods=120).min()
    d["vol50"] = d["Volume"].rolling(50).mean()
    d["red"] = c < c.shift(1)
    d["ret21"] = c / c.shift(21) - 1
    d["ret63"] = c / c.shift(63) - 1
    if bench is not None:
        b = bench.reindex(d.index).ffill()
        d["rs21"] = d["ret21"] - (b / b.shift(21) - 1)
        d["rs63"] = d["ret63"] - (b / b.shift(63) - 1)
    d["low10"] = d["Low"].rolling(10).min()
    return d


def trend_template(row) -> bool:
    """Minervini-style trend template."""
    vals = [row.get(k) for k in ("Close", "sma50", "sma150", "sma200", "sma200_slope20", "hi52", "lo52")]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
        return False
    close, s50, s150, s200, slope, hi, lo = vals
    return (close > s50 > s150 > s200 and slope > 0
            and close >= 0.75 * hi and close >= 1.30 * lo)
