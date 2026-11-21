"""Download ~10 years of daily OHLCV for the Nifty 500 from Yahoo Finance and write one CSV in the
format `pipeline.py build-csv` reads: Date,Ticker,Open,High,Low,Close,Volume.

Standalone: needs only  python -m pip install pandas requests yfinance  (Python 3.10+).

Usage (run on your machine, needs internet):
  python nifty500_downloader.py --start 2016-01-01 --out nifty500_2016_2026.csv
  python nifty500_downloader.py --constituents my_symbols.csv --start 2016-01-01   # CSV with a Symbol column

Prices are auto-adjusted for splits AND dividends (total-return style), so detect/adjust steps
find nothing to fix. Stocks listed after --start have shorter history; delisted stocks are
absent (the constituent list is today's), i.e. survivorship bias remains.
"""
import argparse
import datetime as dt
import io
import sys
import time

import pandas as pd

URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
]
UA = {"User-Agent": "Mozilla/5.0"}
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def load_symbols(path_or_none):
    """Nifty 500 symbols from a local CSV, or downloaded from the first NSE / niftyindices mirror that works."""
    if path_or_none:
        df = pd.read_csv(path_or_none)
    else:
        import requests
        df = None
        for u in URLS:
            try:
                r = requests.get(u, headers=UA, timeout=30)
                if r.status_code == 200 and "Symbol" in r.text[:300]:
                    df = pd.read_csv(io.StringIO(r.text))
                    break
            except Exception as e:  # try next mirror
                print("constituents fetch failed:", u, e, file=sys.stderr)
        if df is None:
            sys.exit("Could not download the Nifty 500 list. Download it from niftyindices.com "
                     "(Nifty 500 constituents CSV) and pass --constituents <file>.")
    col = next(c for c in df.columns if c.strip().lower() in ("symbol", "ticker"))
    return sorted(set(df[col].astype(str).str.strip()))


def to_long(raw: pd.DataFrame, tickers) -> pd.DataFrame:
    """yfinance.download(group_by='ticker') frame -> long format Date,Ticker,O,H,L,C,Volume."""
    parts = []
    for t in tickers:
        yt = t + ".NS"
        if yt not in raw.columns.get_level_values(0):
            continue
        d = raw[yt][FIELDS].dropna(subset=["Close"])
        if d.empty:
            continue
        d = d.reset_index()
        d = d.rename(columns={d.columns[0]: "Date"})
        d["Ticker"] = t
        parts.append(d[["Date", "Ticker"] + FIELDS])
    if not parts:
        return pd.DataFrame(columns=["Date", "Ticker"] + FIELDS)
    out = pd.concat(parts, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"]).dt.tz_localize(None).dt.strftime("%Y-%m-%d")
    return out


def main():
    """CLI: download all symbols from Yahoo Finance in batches (with retries) and write one long CSV."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--out", default="nifty500_2016_2026.csv")
    ap.add_argument("--constituents")
    ap.add_argument("--batch", type=int, default=40)
    a = ap.parse_args()

    import yfinance as yf
    syms = load_symbols(a.constituents)
    print(f"{len(syms)} symbols", flush=True)
    frames, failed = [], []
    for i in range(0, len(syms), a.batch):
        chunk = syms[i:i + a.batch]
        raw = None
        for attempt in range(3):
            try:
                raw = yf.download([s + ".NS" for s in chunk], start=a.start, end=a.end,
                                  interval="1d", auto_adjust=True, group_by="ticker",
                                  threads=True, progress=False)
                break
            except Exception as e:
                print("retry", attempt + 1, e, file=sys.stderr)
                time.sleep(5)
        if raw is None or raw.empty:
            failed += chunk
            continue
        got = to_long(raw, chunk)
        failed += sorted(set(chunk) - set(got["Ticker"]))
        frames.append(got)
        print(f"  {min(i + a.batch, len(syms))}/{len(syms)}", flush=True)
        time.sleep(1)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out.to_csv(a.out, index=False)
    first = out.groupby("Ticker")["Date"].min() if len(out) else pd.Series(dtype=str)
    print(f"wrote {a.out}: {len(out)} rows, {out['Ticker'].nunique() if len(out) else 0} tickers")
    print(f"tickers with history starting after {a.start[:4]}-03: {(first > a.start[:4] + '-03').sum()}")
    if failed:
        print(f"no data for {len(failed)} symbols (renamed/delisted/ticker mismatch): {failed[:30]}")


if __name__ == "__main__":
    main()
