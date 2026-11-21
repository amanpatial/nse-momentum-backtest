"""NSE bhavcopy fetch, ingest and corporate-action adjustment into DuckDB.

Schema of table `ohlc`:
  date, symbol, isin, open, high, low, close, volume, turnover,
  adj_factor, adj_open, adj_high, adj_low, adj_close, adj_volume
`turnover` is traded value in INR. adj_* are back-adjusted for splits/bonuses.
"""

from __future__ import annotations
import datetime as dt
import hashlib
import pathlib
import time
import urllib.request

import duckdb
import numpy as np
import pandas as pd

import paths

HDRS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
KEEP_SERIES = {"EQ", "BE", "BZ"}  # BE/BZ matter: many small caps trade in T2T

LEGACY = {"SYMBOL": "symbol", "SERIES": "series", "OPEN": "open", "HIGH": "high",
          "LOW": "low", "CLOSE": "close", "TOTTRDQTY": "volume",
          "TOTTRDVAL": "turnover", "TIMESTAMP": "date", "ISIN": "isin"}
UDIFF = {"TckrSymb": "symbol", "SctySrs": "series", "OpnPric": "open",
         "HghPric": "high", "LwPric": "low", "ClsPric": "close",
         "TtlTradgVol": "volume", "TtlTrfVal": "turnover", "TradDt": "date",
         "ISIN": "isin"}
COLS = ["date", "symbol", "isin", "open", "high", "low", "close", "volume", "turnover"]


def url_for(d: dt.date) -> str:
    """NSE bhavcopy URL. UNTESTED from the build sandbox (NSE not reachable there);
    NSE switched to the UDiFF format around 8 Jul 2024, verify the cutover date."""
    if d < dt.date(2024, 7, 8):
        mon = d.strftime("%b").upper()
        return ("https://nsearchives.nseindia.com/content/historical/EQUITIES/"
                f"{d.year}/{mon}/cm{d:%d}{mon}{d.year}bhav.csv.zip")
    return ("https://nsearchives.nseindia.com/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")


def fetch(start: dt.date, end: dt.date, out_dir: str, sleep: float = 0.7):
    """Download daily NSE bhavcopy zips into out_dir, skipping weekends, holidays and existing files."""
    import requests
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    miss_file = out / "_missing.txt"
    missing = set(miss_file.read_text().split()) if miss_file.exists() else set()
    s = requests.Session()
    s.headers.update(HDRS)
    s.get("https://www.nseindia.com", timeout=20)  # cookies
    d = start
    while d <= end:
        key = d.isoformat()
        dest = out / f"{d:%Y%m%d}.zip"
        if d.weekday() < 5 and not dest.exists() and key not in missing:
            r = s.get(url_for(d), timeout=30)
            if r.status_code == 200 and r.content[:2] == b"PK":
                dest.write_bytes(r.content)
            elif r.status_code == 404:  # holiday / no file
                missing.add(key)
                miss_file.write_text("\n".join(sorted(missing)))
            elif r.status_code in (403, 429):
                raise RuntimeError(f"NSE blocked request on {key} ({r.status_code}); "
                                   "slow down or retry later")
            time.sleep(sleep)
        d += dt.timedelta(days=1)


def parse_file(p: pathlib.Path) -> pd.DataFrame:
    """Read one bhavcopy file (legacy or UDiFF layout) into standard columns, equity series only."""
    df = pd.read_csv(p, compression="zip" if p.suffix == ".zip" else None)
    df.columns = [c.strip() for c in df.columns]
    if "SYMBOL" in df.columns:
        df = df.rename(columns=LEGACY)
        df["date"] = pd.to_datetime(df["date"].str.strip(), format="%d-%b-%Y")
    elif "TckrSymb" in df.columns:
        df = df.rename(columns=UDIFF)
        df["date"] = pd.to_datetime(df["date"])
    else:
        raise ValueError(f"Unrecognised bhavcopy layout: {p}")
    df["series"] = df["series"].str.strip()
    df["symbol"] = df["symbol"].str.strip()
    df = df[df["series"].isin(KEEP_SERIES)]
    return df[["series"] + COLS]


def read_raw(raw_dir: str) -> pd.DataFrame:
    """Parse every bhavcopy in raw_dir into one table with one row per symbol per day."""
    files = [p for p in sorted(pathlib.Path(raw_dir).iterdir()) if p.suffix in (".csv", ".zip")]
    df = pd.concat([parse_file(p) for p in files], ignore_index=True)
    # one row per symbol/day: keep the most traded series
    df = df.sort_values("volume", ascending=False).drop_duplicates(["date", "symbol"])
    return df[COLS].sort_values(["symbol", "date"]).reset_index(drop=True)


def apply_symbol_map(df: pd.DataFrame, map_csv: str | None) -> pd.DataFrame:
    """map_csv columns: old,new. Renames historical tickers to one stable symbol."""
    if map_csv:
        m = pd.read_csv(map_csv)
        df["symbol"] = df["symbol"].replace(dict(zip(m["old"], m["new"])))
    return df


def adjust(df: pd.DataFrame, ca_csv: str | None) -> pd.DataFrame:
    """Split/bonus-adjust OHLC prices and volume using a corporate actions file.
    corp_actions.csv columns: symbol,ex_date,factor.
    factor is the price multiplier applied to all dates BEFORE ex_date
    (5-for-1 split -> 0.2; 1:1 bonus -> 0.5; use the exchange's adjustment factor
    for rights/demergers)."""
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["adj_factor"] = 1.0
    if ca_csv:
        ca = pd.read_csv(ca_csv, parse_dates=["ex_date"])
        for sym, g in ca.groupby("symbol"):
            m = (df["symbol"] == sym).to_numpy()
            if not m.any():
                continue
            d = df.loc[m, "date"].to_numpy()
            f = np.ones(m.sum())
            for ex, fac in zip(g["ex_date"], g["factor"]):
                f[d < np.datetime64(ex)] *= fac
            df.loc[m, "adj_factor"] = f
    for c in ("open", "high", "low", "close"):
        df[f"adj_{c}"] = df[c] * df["adj_factor"]
    df["adj_volume"] = df["volume"] / df["adj_factor"]
    return df


def build_db(raw_dir, db_path, ca_csv=None, map_csv=None, universe_csv=None, parquet_path=None):
    """Build the DuckDB ohlc table from raw bhavcopies (rename, universe filter, split-adjust)."""
    df = read_raw(raw_dir)
    df = apply_symbol_map(df, map_csv)
    if universe_csv:
        keep = set(pd.read_csv(universe_csv)["symbol"])
        df = df[df["symbol"].isin(keep)]
    df = adjust(df, ca_csv)
    con = duckdb.connect(db_path)
    con.register("o", df)
    con.execute("create or replace table ohlc as select * from o")
    if parquet_path:
        con.execute(f"copy ohlc to '{parquet_path}' (format parquet)")
    n = con.execute("select count(*), count(distinct symbol), min(date), max(date) from ohlc").fetchone()
    con.close()
    return n


def checks(db_path):
    """Returns dict of DataFrames: suspicious returns, short histories, zero-volume days."""
    con = duckdb.connect(db_path, read_only=True)
    out = {
        "big_moves": con.execute("""
            with r as (select symbol, date,
                       adj_close / lag(adj_close) over (partition by symbol order by date) - 1 as ret
                       from ohlc)
            select * from r where abs(ret) > 0.30 order by abs(ret) desc limit 100""").df(),
        "coverage": con.execute("""
            select symbol, count(*) as days, min(date) as first, max(date) as last
            from ohlc group by 1 order by days""").df(),
        "zero_volume": con.execute("""
            select symbol, count(*) as zero_vol_days from ohlc
            where volume = 0 group by 1 order by 2 desc limit 50""").df(),
    }
    con.close()
    return out


# ---------- Loader for single-CSV datasets (e.g. IITKGP/Nifty500_companies_5_years_data) ----------
# Option A source: public, MIT-licensed. The SHA-256 pins the exact file behind every README result.
PRICES_URL = ("https://huggingface.co/datasets/IITKGP/Nifty500_companies_5_years_data"
              "/resolve/main/nifty500_5yr_data.csv")
PRICES_SHA256 = "74ad16d3135685880ccde748bffe58da0d13b255f190443a9f7a3b0200b648eb"


def sha256_of(path) -> str:
    """SHA-256 hex digest of a file, read in 1 MB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_prices_csv(dest=paths.PRICES_CSV, url: str = PRICES_URL, sha256: str = PRICES_SHA256,
                        force: bool = False) -> pathlib.Path:
    """Download the Option A price CSV to dest and verify its SHA-256; skip if a verified copy exists.
    Writes to dest + '.part' first and renames only after the checksum matches, so an interrupted or
    changed download never leaves a bad file in place. Raises RuntimeError on a checksum mismatch."""
    dest = pathlib.Path(dest)
    if dest.exists() and not force:
        if sha256_of(dest) == sha256:
            print(f"{dest} already present (checksum OK)")
            return dest
        raise RuntimeError(f"{dest} exists but its checksum does not match the pinned dataset. "
                           "Delete it or rerun with --force to download a fresh copy.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h, done, last_pct = hashlib.sha256(), 0, -10
    print(f"downloading {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nse-momentum-backtest"})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            for chunk in iter(lambda: r.read(1 << 20), b""):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                pct = int(done * 100 / total) if total else -1
                if pct >= last_pct + 10:
                    print(f"  {done / 1e6:.0f} / {total / 1e6:.0f} MB ({pct}%)", flush=True)
                    last_pct = pct
        if h.hexdigest() != sha256:
            raise RuntimeError(f"checksum mismatch for {url}: got {h.hexdigest()}, expected {sha256}. "
                               "The source file may have changed; results would not match the README.")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    print(f"saved {dest} ({done / 1e6:.1f} MB, checksum OK)")
    return dest

# Columns: Date, Ticker, Open, High, Low, Close, Volume[, Notes]. No turnover, no adjustment info.
SPLIT_RATIOS = [1/2, 1/3, 1/4, 1/5, 1/10, 2/3, 3/4]  # price ratio on ex-date: splits, 1:1/2:1/1:2 bonuses


def read_csv_dataset(path: str) -> pd.DataFrame:
    """Load the Nifty500 CSV dataset into standard columns (turnover = close x volume)."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns={"ticker": "symbol"})
    df["symbol"] = df["symbol"].astype(str).str.strip().str.replace(r"\.NS$", "", regex=True)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df["isin"] = None
    df["turnover"] = df["close"] * df["volume"]  # proxy: no value column in this dataset
    df = df.dropna(subset=["close"]).drop_duplicates(["date", "symbol"])
    return df[COLS].sort_values(["symbol", "date"]).reset_index(drop=True)


def detect_corp_actions(df: pd.DataFrame, tol: float = 0.04) -> pd.DataFrame:
    """Flag likely unadjusted splits/bonuses: a one-day close ratio near a standard ratio
    AND volume jumping by roughly the inverse ratio. REVIEW the output; a genuine crash
    with heavy volume can look the same. Returns symbol, ex_date, factor, ratio, vol_ratio."""
    g = df.sort_values(["symbol", "date"]).copy()
    g["ratio"] = g["close"] / g.groupby("symbol")["close"].shift()
    g["vol_ratio"] = g["volume"] / g.groupby("symbol")["volume"].shift().replace(0, np.nan)
    rows = []
    for _, r in g[g["ratio"] < 0.80].iterrows():
        for s in SPLIT_RATIOS:
            if abs(r["ratio"] - s) <= tol * s and r["vol_ratio"] >= 0.7 / s:
                rows.append((r["symbol"], r["date"], s, r["ratio"], r["vol_ratio"]))
                break
    return pd.DataFrame(rows, columns=["symbol", "ex_date", "factor", "ratio", "vol_ratio"])


def drop_rows(df: pd.DataFrame, drop_csv: str | None) -> pd.DataFrame:
    """Remove known-bad rows listed in drop_csv (columns: symbol,start,end[,reason]; dates inclusive).
    For data-source glitches that are not corporate actions: stale frozen quotes, mispriced sessions."""
    if not drop_csv:
        return df
    bad = pd.read_csv(drop_csv, parse_dates=["start", "end"])
    mask = pd.Series(False, index=df.index)
    for r in bad.itertuples():
        mask |= (df["symbol"] == r.symbol) & (df["date"] >= r.start) & (df["date"] <= r.end)
    print(f"dropped {int(mask.sum())} bad rows listed in {drop_csv}")
    return df[~mask].reset_index(drop=True)


def build_db_from_csv(csv_path, db_path, auto_adjust=False, ca_csv=None,
                      detected_out=str(paths.DETECTED_ACTIONS), universe_csv=None, drop_csv=None):
    """Build the DuckDB ohlc table from the CSV dataset: drop listed bad rows, flag and apply splits."""
    df = drop_rows(read_csv_dataset(csv_path), drop_csv)
    if universe_csv:
        df = df[df["symbol"].isin(set(pd.read_csv(universe_csv)["symbol"]))]
    det = detect_corp_actions(df)
    det.to_csv(detected_out, index=False)
    use = ca_csv
    if auto_adjust and len(det):
        det[["symbol", "ex_date", "factor"]].to_csv(detected_out + ".apply.csv", index=False)
        use = detected_out + ".apply.csv"
    df = adjust(df, use)
    con = duckdb.connect(db_path)
    con.register("o", df)
    con.execute("create or replace table ohlc as select * from o")
    n = con.execute("select count(*), count(distinct symbol), min(date), max(date) from ohlc").fetchone()
    con.close()
    return n, len(det)
