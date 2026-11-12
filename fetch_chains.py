#!/usr/bin/env python3
"""Option chain snapshot for the Helio Desk (v2). Writes data/chains.json.

For each ticker in chains.txt: expiries 55 to 125 days out (at most 3), strikes from
15% under to 20% over spot, calls and puts, with bid, ask, last, open interest, volume, IV.
Yahoo shows zero bids outside market hours, so a ticker's saved chain is only replaced
when the new one has at least one live bid. Price data only: no holdings, no calls.

Usage: python fetch_chains.py [--list chains.txt] [--out data/chains.json]
"""
import argparse
import json
import math
from datetime import date, datetime, timezone

import yfinance as yf


def num(v, nd=4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else round(f, nd)


def rows(df, lo, hi):
    out = []
    for r in df.itertuples():
        k = num(r.strike)
        if k is None or k < lo or k > hi:
            continue
        out.append({"k": k, "bid": num(r.bid, 2), "ask": num(r.ask, 2), "last": num(r.lastPrice, 2),
                    "oi": int(num(r.openInterest, 0) or 0), "vol": int(num(r.volume, 0) or 0),
                    "iv": num(r.impliedVolatility, 4)})
    return out


def one(sym, today):
    tk = yf.Ticker(sym)
    spot = num(tk.history(period="5d")["Close"].dropna().iloc[-1])
    exps = []
    for e in tk.options:
        dte = (date.fromisoformat(e) - today).days
        if 55 <= dte <= 125:
            exps.append((e, dte))
    if not exps:
        raise ValueError("no expiry 55 to 125 days out")
    out = {"spot": spot, "expiries": {}}
    for e, dte in exps[:3]:
        ch = tk.option_chain(e)
        out["expiries"][e] = {"dte": dte, "calls": rows(ch.calls, spot * 0.85, spot * 1.20),
                              "puts": rows(ch.puts, spot * 0.85, spot * 1.20)}
    return out


def live(chain):
    return any((r.get("bid") or 0) > 0 for e in chain["expiries"].values() for side in ("calls", "puts") for r in e[side])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="chains.txt")
    ap.add_argument("--out", default="data/chains.json")
    a = ap.parse_args()
    syms = [l.strip().upper() for l in open(a.list) if l.strip() and not l.startswith("#")]
    try:
        old = json.load(open(a.out)).get("chains", {})
    except (FileNotFoundError, ValueError):
        old = {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chains, errors = {}, {}
    for s in syms:
        try:
            c = one(s, date.today())
            if live(c) or s not in old:
                c["quoted_utc"] = now
                c["live_bids"] = live(c)
                chains[s] = c
            else:
                chains[s] = old[s]  # keep the last snapshot that had live bids
        except Exception as e:
            errors[s] = str(e)[:200]
            if s in old:
                chains[s] = old[s]
    out = {"generated_utc": now,
           "source": "Yahoo Finance via yfinance, delayed quotes; check the real chain before any order",
           "chains": chains, "errors": errors}
    with open(a.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"wrote {len(chains)} chains, {len(errors)} errors -> {a.out}")


if __name__ == "__main__":
    main()
