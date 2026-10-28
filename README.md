# Daily price snapshot

A GitHub Actions job fetches daily bars from Yahoo Finance (through the `yfinance` library) and commits `data/prices.json`: last close, 10/20/50/150/200-day averages, 200-day slope, 52-week high and low, volume vs the 50-day average, red-day flag, 1 and 3-month return and relative strength vs SPY (BTC for crypto), a trend-template flag and the last 10 bars, for a core list of indexes, sectors, rates, commodities and crypto plus the tickers in `watchlist.txt`.

Schedule: weekdays at 11:05 and 21:30 UTC, plus on demand. Data is free, unofficial and delayed. Use it for daily levels, not for live quotes.

Read it at `https://raw.githubusercontent.com/<owner>/<repo>/main/data/prices.json`.

## History

`fetch_history.py` writes `history/daily.csv.gz` (five years of daily bars for the tickers in `universe.txt` and `watchlist.txt`, plus SPY, QQQ, BTC-USD and ETH-USD) and `history/earnings.json` (past and announced earnings dates from Yahoo). It runs with the Friday after-close job and on demand.
