#!/usr/bin/env python3
"""AI supply chain snapshot: price structure plus growth and estimate data per ticker.

Reads ai_universe.txt (ticker and layer per line) and writes data/ai_scan.json with raw
metrics only: trend and relative strength, base and pivot, up/down volume, revenue growth
by quarter, analyst estimate trends and revisions, and the next earnings date. Ranking
is left to whoever reads the file.

Fundamentals take several Yahoo requests per ticker, so they are reused from the last
file when younger than --fund-max-age-h hours (the after-close run reuses the morning's).

Usage: python fetch_ai.py [--universe ai_universe.txt] [--out data/ai_scan.json]
                          [--fund-max-age-h 20]
"""
import argparse
import json
import math
import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from fetch_prices import clean, snapshot

BENCH = ["SPY", "QQQ", "SMH"]


def universe(path):
    rows = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        rows.append((parts[0].upper(), parts[1] if len(parts) > 1 else "other"))
    return rows


def ret(c, n):
    return clean(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None


def structure(df, smh):
    """Price structure beyond the standard snapshot."""
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    out = {f"ret{n}": ret(c, n) for n in (5, 126, 189, 252)}
    s = smh.reindex(df.index).ffill()
    out["rs63_smh"] = clean(c.iloc[-1] / c.iloc[-64] - s.iloc[-1] / s.iloc[-64]) if len(c) > 64 else None
    chg = c.diff()
    last50 = slice(-50, None)
    upv = v[last50][chg[last50] > 0].sum()
    dnv = v[last50][chg[last50] < 0].sum()
    out["ud_vol_50"] = clean(upv / dnv) if dnv else None
    vol50 = v.rolling(50).mean()
    last25 = slice(-25, None)
    heavy = v[last25] > vol50[last25]
    out["accum_days_25"] = int(((chg[last25] > 0) & heavy).sum())
    out["dist_days_25"] = int(((chg[last25] < 0) & heavy).sum())
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    out["atr14_pct"] = clean(tr.rolling(14).mean().iloc[-1] / c.iloc[-1] * 100)
    out["dollar_vol50"] = clean((c * v).rolling(50).mean().iloc[-1])
    # Base: the 35 sessions before today. Pivot is their high, depth their range.
    if len(df) > 40:
        win = df.iloc[-36:-1]
        pivot, base_low = float(win["High"].max()), float(win["Low"].min())
        out["pivot"] = clean(pivot)
        out["pivot_date"] = win["High"].idxmax().strftime("%Y-%m-%d")
        out["base_low"] = clean(base_low)
        out["base_depth"] = clean(1 - base_low / pivot)
        last10 = c.iloc[-10:]
        out["tight10"] = clean(last10.max() / last10.min() - 1)
        out["pct_vs_pivot"] = clean(c.iloc[-1] / pivot - 1)
    # Swing low of the last 5 sessions, for pullback stops.
    out["low5"] = clean(l.iloc[-5:].min())
    out["high20"] = clean(h.iloc[-20:].max())
    return out


def frame_dict(df):
    if df is None or not hasattr(df, "to_dict") or len(df) == 0:
        return None
    df = df.replace({np.nan: None})
    return {str(k): {str(c): clean(x) if not isinstance(x, str) else x for c, x in row.items()}
            for k, row in df.to_dict(orient="index").items()}


def revenue_history(t):
    for attr in ("quarterly_income_stmt", "quarterly_financials"):
        try:
            q = getattr(t, attr)
            if q is not None and len(q) and "Total Revenue" in q.index:
                r = q.loc["Total Revenue"].dropna().sort_index()
                return [{"end": d.strftime("%Y-%m-%d"), "revenue": clean(x)} for d, x in r.items()][-8:]
        except Exception:
            continue
    return None


def fundamentals(sym):
    t = yf.Ticker(sym)
    out, errs = {"fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, {}
    try:
        info = t.info or {}
        for k in ("shortName", "sector", "industry", "currency", "marketCap", "revenueGrowth",
                  "earningsGrowth", "grossMargins", "operatingMargins", "forwardPE", "trailingPE",
                  "heldPercentInstitutions", "shortPercentOfFloat", "numberOfAnalystOpinions",
                  "recommendationMean", "targetMeanPrice"):
            out[k] = clean(info.get(k)) if not isinstance(info.get(k), str) else info.get(k)
    except Exception as e:
        errs["info"] = str(e)[:120]
    try:
        out["revenue_q"] = revenue_history(t)
    except Exception as e:
        errs["revenue_q"] = str(e)[:120]
    for name in ("revenue_estimate", "earnings_estimate", "eps_trend", "eps_revisions", "earnings_history"):
        try:
            out[name] = frame_dict(getattr(t, name))
        except Exception as e:
            errs[name] = str(e)[:120]
    try:
        cal = t.calendar or {}
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        out["next_earnings"] = [d.strftime("%Y-%m-%d") for d in dates] if dates else None
    except Exception as e:
        errs["calendar"] = str(e)[:120]
    if errs:
        out["errors"] = errs
    return out


def age_hours(stamp):
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except Exception:
        return math.inf
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="ai_universe.txt")
    ap.add_argument("--out", default="data/ai_scan.json")
    ap.add_argument("--fund-max-age-h", type=float, default=20)
    a = ap.parse_args()
    rows = universe(a.universe)
    syms = list(dict.fromkeys(BENCH + [s for s, _ in rows]))
    raw = yf.download(syms, period="2y", interval="1d", group_by="ticker", auto_adjust=True,
                      progress=False, threads=True)
    spy = raw["SPY"]["Close"].dropna()
    smh = raw["SMH"]["Close"].dropna()
    old = {}
    if os.path.exists(a.out):
        try:
            old = json.load(open(a.out)).get("symbols", {})
        except Exception:
            old = {}
    result, errors, fetched = {}, {}, 0
    for sym, layer in rows:
        try:
            df = raw[sym].dropna(subset=["Close"])
            if len(df) < 30:
                raise ValueError("not enough history")
            rec = snapshot(sym, df, spy)
            rec.update(structure(df, smh))
            rec["layer"] = layer
            rec["history_days"] = len(df)
        except Exception as e:
            errors[sym] = str(e)[:200]
            continue
        if layer != "bench":
            prev = old.get(sym, {}).get("fund")
            if prev and age_hours(prev.get("fetched_utc", "")) < a.fund_max_age_h:
                rec["fund"] = prev
            else:
                try:
                    rec["fund"] = fundamentals(sym)
                    fetched += 1
                except Exception as e:
                    errors[f"{sym} fundamentals"] = str(e)[:200]
                    if prev:
                        rec["fund"] = prev
                time.sleep(0.4)
        result[sym] = rec
    out = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance via yfinance: daily bars (auto-adjusted), statements, analyst estimates",
        "fundamentals_refreshed": fetched,
        "bench": {b: snapshot(b, raw[b].dropna(subset=["Close"]), spy) for b in BENCH},
        "symbols": result,
        "errors": errors,
    }
    with open(a.out, "w") as f:
        json.dump(out, f, indent=0, default=str)
    print(f"ai scan: {len(result)} symbols, {fetched} fundamentals refreshed, {len(errors)} errors -> {a.out}")


if __name__ == "__main__":
    main()
