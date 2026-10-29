# Daily price snapshot

A GitHub Actions job fetches daily bars from Yahoo Finance (through the `yfinance` library) and commits `data/prices.json`: last close, 10/20/50/150/200-day averages, 200-day slope, 52-week high and low, volume vs the 50-day average, red-day flag, 1 and 3-month return and relative strength vs SPY (BTC for crypto), a trend-template flag and the last 10 bars, for a core list of indexes, sectors, rates, commodities and crypto plus the tickers in `watchlist.txt`.

Schedule: weekdays at 11:05 and 21:30 UTC, plus on demand. Data is free, unofficial and delayed. Use it for daily levels, not for live quotes.

Read it at `https://raw.githubusercontent.com/<owner>/<repo>/main/data/prices.json`.

## History

`fetch_history.py` writes `history/daily.csv.gz` (five years of daily bars for the tickers in `universe.txt` and `watchlist.txt`, plus SPY, QQQ, BTC-USD and ETH-USD) and `history/earnings.json` (past and announced earnings dates from Yahoo). It runs with the Friday after-close job and on demand.

## AI scan

`fetch_ai.py` writes `data/ai_scan.json` for the tickers in `ai_universe.txt` (ticker and supply-chain layer per line): the same snapshot fields as `prices.json` plus 5/126/189/252-day returns, 3-month return vs SMH, 50-day up/down volume ratio, heavy-volume up and down days over 25 sessions, ATR, dollar volume, the 35-session base (pivot, base low, depth, 10-day tightness, distance from pivot), and from Yahoo: quarterly revenue, revenue and EPS estimates, EPS estimate trend (now vs 7/30/60/90 days ago), revision counts, the last four EPS surprises and the next earnings date. Raw metrics only. It runs with both daily jobs; fundamentals refresh when the stored ones are over 20 hours old, so the morning run fetches and the after-close run reuses them. Also per name: the last five sessions (change, volume vs the 50-day, high, low, close), the last report date from `history/earnings.json`, and for names listed inside the two-year window, the listing date, high since listing and distance from it. For MSFT, GOOGL, AMZN, META, ORCL, CRWV and NBIS it adds quarterly capital expenditure.
