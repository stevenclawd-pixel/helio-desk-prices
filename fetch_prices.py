#!/usr/bin/env python3
"""Daily price snapshot for the Helio Desk. Runs on GitHub Actions (or any machine
that can reach Yahoo Finance), writes data/prices.json.

Usage: python fetch_prices.py [--watchlist watchlist.txt] [--out data/prices.json]
"""
import argparse
import json
import math
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from indicators import add_indicators, trend_template

CORE = ["SPY", "QQQ", "IWM", "RSP", "^VIX", "^VIX3M", "^TNX", "DX-Y.NYB", "CL=F", "GC=F",
        "CAD=X", "BTC-USD", "ETH-USD", "XLK", "XLE", "XLF", "XLV", "XLP", "XLU", "XLI", "XLY", "XLC", "SMH"]


def clean(v):
    if v is None:
        return None
    if isinstance(v, (bool,)):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if math.isnan(f) else round(f, 4)


def snapshot(sym, df, bench):
    d = add_indicators(df, bench)
    last, prev = d.iloc[-1], d.iloc[-2]
    out = {k: clean(last.get(k)) for k in ("Close", "sma10", "sma20", "sma50", "sma150", "sma200",
                                          "sma200_slope20", "hi52", "lo52", "vol50", "ret21", "ret63",
                                          "rs21", "rs63", "low10")}
    out.update({
        "date": d.index[-1].strftime("%Y-%m-%d"),
        "change_pct": clean((last["Close"] / prev["Close"] - 1) * 100),
        "red_day": bool(last["Close"] < prev["Close"]),
        "volume": clean(last["Volume"]),
        "vol_vs_50d": clean(last["Volume"] / last["vol50"]) if last.get("vol50") else None,
        "pct_from_hi52": clean((last["Close"] / last["hi52"] - 1) * 100) if last.get("hi52") else None,
        "trend_template": bool(trend_template(last)),
        "bars": [{"date": i.strftime("%Y-%m-%d"), "o": clean(r.Open), "h": clean(r.High),
                  "l": clean(r.Low), "c": clean(r.Close)} for i, r in d.tail(10).iterrows()],
    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist", default="watchlist.txt")
    ap.add_argument("--out", default="data/prices.json")
    a = ap.parse_args()
    try:
        extra = [l.strip().upper() for l in open(a.watchlist) if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        extra = []
    syms = list(dict.fromkeys(CORE + extra))
    raw = yf.download(syms, period="2y", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
    spy = raw["SPY"]["Close"].dropna()
    btc = raw["BTC-USD"]["Close"].dropna()
    result, errors = {}, {}
    for s in syms:
        try:
            df = raw[s].dropna(subset=["Close"])
            if len(df) < 30:
                raise ValueError("not enough history")
            bench = btc if s.endswith("-USD") else spy
            result[s] = snapshot(s, df, bench)
        except Exception as e:  # keep going; failed symbols are listed in errors
            errors[s] = str(e)[:200]
    vix, vix3m = result.get("^VIX", {}).get("Close"), result.get("^VIX3M", {}).get("Close")
    eth, btcp = result.get("ETH-USD", {}).get("Close"), result.get("BTC-USD", {}).get("Close")
    out = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance via yfinance, daily bars, auto-adjusted",
        "derived": {
            "vix_vix3m": clean(vix / vix3m) if vix and vix3m else None,
            "eth_btc": clean(eth / btcp) if eth and btcp else None,
            "rsp_vs_spy_21d": clean((result.get("RSP", {}).get("ret21") or 0) - (result.get("SPY", {}).get("ret21") or 0)),
        },
        "symbols": result,
        "errors": errors,
    }
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {len(result)} symbols, {len(errors)} errors -> {a.out}")


if __name__ == "__main__":
    main()
