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
    # Last five sessions, for earnings reaction days.
    out["recent"] = [{"date": i.strftime("%Y-%m-%d"), "chg": clean(chg.loc[i] / c.shift().loc[i]),
                      "vol_ratio": clean(v.loc[i] / vol50.shift().loc[i]), "high": clean(h.loc[i]),
                      "low": clean(l.loc[i]), "close": clean(c.loc[i])} for i in df.index[-5:]]
    return out


def since_listing(df, start):
    """For names listed inside the download window: the IPO high and how far price sits from it."""
    first = df.index[0]
    if (first - start).days < 10:
        return None
    c, h, l = df["Close"], df["High"], df["Low"]
    hi_day = h.idxmax()
    after = l.loc[hi_day:]
    return {"first_date": first.strftime("%Y-%m-%d"), "sessions": len(df), "first_close": clean(c.iloc[0]),
            "high": clean(h.max()), "high_date": hi_day.strftime("%Y-%m-%d"),
            "low_since_high": clean(after.min()), "low": clean(l.min()),
            "pct_from_high": clean(c.iloc[-1] / h.max() - 1), "pct_vs_first_close": clean(c.iloc[-1] / c.iloc[0] - 1)}


def report_dates(path):
    try:
        return json.load(open(path)).get("dates", {})
    except Exception:
        return {}


def capex_history(t):
    for attr in ("quarterly_cashflow", "quarterly_cash_flow"):
        try:
            q = getattr(t, attr)
            if q is not None and len(q) and "Capital Expenditure" in q.index:
                r = q.loc["Capital Expenditure"].dropna().sort_index()
                return [{"end": d.strftime("%Y-%m-%d"), "capex": clean(-x)} for d, x in r.items()][-8:]
        except Exception:
            continue
    return None


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


CAPEX = {"MSFT", "GOOGL", "AMZN", "META", "ORCL", "CRWV", "NBIS"}


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
    if sym in CAPEX:
        try:
            out["capex_q"] = capex_history(t)
        except Exception as e:
            errs["capex_q"] = str(e)[:120]
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


def bench_df(df, in_session, today):
    df = df.dropna(subset=["Close"])
    if in_session and len(df) and df.index[-1].strftime("%Y-%m-%d") == today:
        df = df.iloc[:-1]
    return df


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
    ap.add_argument("--earnings", default="history/earnings.json")
    a = ap.parse_args()
    rows = universe(a.universe)
    syms = list(dict.fromkeys(BENCH + [s for s, _ in rows]))
    raw = yf.download(syms, period="2y", interval="1d", group_by="ticker", auto_adjust=True,
                      progress=False, threads=True)
    spy = raw["SPY"]["Close"].dropna()
    smh = raw["SMH"]["Close"].dropna()
    start = raw.index[0]
    reports = report_dates(a.earnings)
    old = {}
    if os.path.exists(a.out):
        try:
            old = json.load(open(a.out)).get("symbols", {})
        except Exception:
            old = {}
    now = datetime.now(timezone.utc)
    # A run during US market hours would score a partial bar; keep the prior close instead.
    in_session = now.weekday() < 5 and (13, 30) <= (now.hour, now.minute) < (21, 0)
    today = now.strftime("%Y-%m-%d")
    result, errors, fetched = {}, {}, 0
    for sym, layer in rows:
        try:
            df = raw[sym].dropna(subset=["Close"])
            if in_session and len(df) and df.index[-1].strftime("%Y-%m-%d") == today:
                df = df.iloc[:-1]
            if len(df) < 30:
                raise ValueError("not enough history")
            rec = snapshot(sym, df, spy)
            rec.update(structure(df, smh))
            rec["layer"] = layer
            rec["history_days"] = len(df)
            rec["since_listing"] = since_listing(df, start)
            past = sorted(d for d in reports.get(sym, []) if d <= today)
            rec["last_report"] = past[-1] if past else None
        except Exception as e:
            errors[sym] = str(e)[:200]
            continue
        if layer != "bench":
            prev = old.get(sym, {}).get("fund")
            if prev and age_hours(prev.get("fetched_utc", "")) < a.fund_max_age_h and (sym not in CAPEX or "capex_q" in prev):
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
        "partial_bar_dropped": in_session,
        "bench": {b: snapshot(b, bench_df(raw[b], in_session, today), spy) for b in BENCH},
        "symbols": result,
        "errors": errors,
    }
    with open(a.out, "w") as f:
        json.dump(out, f, indent=0, default=str)
    print(f"ai scan: {len(result)} symbols, {fetched} fundamentals refreshed, {len(errors)} errors -> {a.out}")


if __name__ == "__main__":
    main()
