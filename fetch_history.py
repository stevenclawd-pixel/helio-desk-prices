#!/usr/bin/env python3
"""Daily bar history and earnings dates for a list of tickers.

Writes history/daily.csv.gz (symbol,date,open,high,low,close,volume; auto-adjusted)
and history/earnings.json ({"generated_utc", "dates": {symbol: [YYYY-MM-DD, ...]}}).
Earnings dates are refreshed only when the file is older than 6 days, because each
ticker needs its own request.

Usage: python fetch_history.py [--years 5] [--out history]
"""
import argparse
import csv
import gzip
import io
import json
import os
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

BASE = ["SPY", "QQQ", "ETH-USD", "BTC-USD"]


def tickers(*files):
    out = []
    for f in files:
        try:
            out += [l.strip().upper() for l in open(f) if l.strip() and not l.startswith("#")]
        except FileNotFoundError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--out", default="history")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    syms = list(dict.fromkeys(BASE + tickers("universe.txt", "watchlist.txt")))
    raw = yf.download(syms, period=f"{a.years}y", interval="1d", group_by="ticker",
                      auto_adjust=True, progress=False, threads=True)
    buf, loaded, errors = io.StringIO(), [], {}
    w = csv.writer(buf)
    w.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
    for s in syms:
        try:
            df = raw[s].dropna(subset=["Close"])
            if len(df) < 30:
                raise ValueError("not enough history")
        except Exception as e:
            errors[s] = str(e)[:200]
            continue
        loaded.append(s)
        for t, r in df.iterrows():
            w.writerow([s, t.strftime("%Y-%m-%d"), round(r.Open, 4), round(r.High, 4), round(r.Low, 4),
                        round(r.Close, 4), int(r.Volume) if r.Volume == r.Volume else 0])
    with open(f"{a.out}/daily.csv.gz", "wb") as f:  # mtime=0 keeps the file stable when the data is
        f.write(gzip.compress(buf.getvalue().encode(), compresslevel=9, mtime=0))

    epath = f"{a.out}/earnings.json"
    old = json.load(open(epath)) if os.path.exists(epath) else {}
    age = None
    if old.get("generated_utc"):
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(old["generated_utc"].replace("Z", "+00:00"))).days
    dates = dict(old.get("dates", {}))
    if age is None or age >= 6 or any(s not in dates for s in loaded):
        for s in loaded:
            if s.endswith("-USD") or s in ("SPY", "QQQ"):
                continue
            if age is not None and age < 6 and s in dates:
                continue
            try:
                ed = yf.Ticker(s).get_earnings_dates(limit=28)
                if ed is not None and len(ed):
                    dates[s] = sorted({pd.Timestamp(t).tz_localize(None).strftime("%Y-%m-%d") for t in ed.index})
            except Exception as e:
                errors[f"{s} earnings"] = str(e)[:200]
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        stamp = old["generated_utc"]
    json.dump({"generated_utc": stamp, "dates": dates}, open(epath, "w"), indent=0, sort_keys=True)
    meta = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "years": a.years, "symbols": loaded, "errors": errors}
    json.dump(meta, open(f"{a.out}/meta.json", "w"), indent=1)
    print(f"history: {len(loaded)} symbols, {len(errors)} errors, earnings for {len(dates)}")


if __name__ == "__main__":
    main()
