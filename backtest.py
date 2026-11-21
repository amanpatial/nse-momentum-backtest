"""Monthly cross-sectional momentum backtest on the adjusted OHLC database.

RULES: rank by trailing 3-month return; hold top 20 equal weight; month-end review;
holdings ranked 21-30 are kept (time to come back), sold only below rank 30; vacancies
are filled from the best-ranked non-held stocks. Liquidity filter, optional volatility
filter (drop the most volatile stocks before ranking), flat cost.
Signals use data up to the rebalance close; positions start the next trading day
(no lookahead).
"""

from __future__ import annotations
from dataclasses import dataclass, asdict

import duckdb
import numpy as np
import pandas as pd


@dataclass
class Cfg:
    """Strategy settings: ranking, portfolio size, liquidity/volatility filters, costs, dates."""
    lookback: int = 63         # ~3 months of trading days
    skip: int = 0              # no skip: rank on the last 3 months
    top_n: int = 20            # portfolio size
    buffer: int = 30           # a holding is sold only if its rank falls below this
    min_adtv_cr: float = 0.5   # min 20d avg traded value, INR crore
    adtv_window: int = 20
    max_vol_pctile: float = 1.0  # volatility filter: keep stocks at or below this percentile of
                                 # trailing vol among eligible stocks (0.8 = drop top 20%); 1.0 = off
    vol_window: int = 63       # trading days for trailing annualised volatility
    vol_freq: str = "daily"    # returns used for volatility: "daily" or "weekly" (5-trading-day)
    cost_bps: float = 40.0     # per unit of one-way turnover (fees+STT+impact)
    start: str = "2016-04-01"
    end: str | None = None


def load_panel(db_path):
    """Load adjusted closes and traded value from DuckDB as date x symbol tables."""
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("select date, symbol, adj_close, turnover from ohlc").df()
    con.close()
    px = df.pivot(index="date", columns="symbol", values="adj_close").sort_index()
    to = df.pivot(index="date", columns="symbol", values="turnover").sort_index()
    return px, to


EXIT_INELIGIBLE = "ineligible (illiquid / unpriced / too volatile)"   # trade-log exit reason


def month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each month in the index (the default review dates)."""
    return index.to_series().groupby([index.year, index.month]).tail(1).index


def signals(px: pd.DataFrame, to: pd.DataFrame, cfg: Cfg):
    """Inputs for ranking: gap-filled prices, momentum signal, ADTV (Rs crore), volatility (None if off).
    Every engine (run, trade export, stop-loss simulator) uses this, so they rank identically."""
    px_f = px.ffill(limit=5)  # bridge short gaps only; longer gaps = suspended
    sig = px_f.shift(cfg.skip) / px_f.shift(cfg.lookback) - 1
    adtv = to.rolling(cfg.adtv_window, min_periods=cfg.adtv_window // 2).mean() / 1e7
    vol = volatility(px_f, cfg) if cfg.max_vol_pctile < 1.0 else None
    return px_f, sig, adtv, vol


def volatility(px_f: pd.DataFrame, cfg: Cfg) -> pd.DataFrame:
    """Trailing annualised volatility over the last cfg.vol_window trading days (needs 80% of the data).
    daily : std of the daily returns in the window x sqrt(252).
    weekly: std of the non-overlapping 5-trading-day returns ending on each date
            (d-5..d, d-10..d-5, ...; round(vol_window / 5) of them, 63 days -> 13 weeks) x sqrt(52).
            Weeks are anchored on the review date itself, so no future data is used."""
    if cfg.vol_freq == "daily":
        r = px_f.pct_change(fill_method=None)
        return r.rolling(cfg.vol_window, min_periods=int(cfg.vol_window * 0.8)).std() * np.sqrt(252)
    if cfg.vol_freq == "weekly":
        n = max(round(cfg.vol_window / 5), 2)
        r5 = px_f / px_f.shift(5) - 1
        weeks = [r5.shift(5 * k) for k in range(n)]
        cnt = sum(w.notna().astype(int) for w in weeks)
        mean = sum(w.fillna(0.0) for w in weeks) / cnt
        var = sum(((w - mean) ** 2).fillna(0.0) for w in weeks) / (cnt - 1)
        return (np.sqrt(var) * np.sqrt(52)).where(cnt >= int(n * 0.8))
    raise ValueError(f"vol_freq must be 'daily' or 'weekly', got {cfg.vol_freq!r}")


def ranked_eligible(d, sig: pd.DataFrame, adtv: pd.DataFrame, px: pd.DataFrame,
                    vol: pd.DataFrame | None, cfg: Cfg) -> pd.Series:
    """Eligible stocks on review date d, sorted by signal (best first).
    Eligible = priced on d, has a signal, 20d ADTV >= min_adtv_cr, and (if the volatility filter
    is on) trailing vol <= the max_vol_pctile percentile of the liquid stocks' vol on d.
    A holding that fails the filter is no longer eligible, so it is sold (same as illiquid)."""
    s = sig.loc[d]
    ok = (adtv.loc[d] >= cfg.min_adtv_cr) & s.notna() & px.loc[d].notna()
    if vol is not None and cfg.max_vol_pctile < 1.0:
        v = vol.loc[d]
        cap = v[ok].quantile(cfg.max_vol_pctile)
        ok &= v.notna() & (v <= cap)
    return s[ok].sort_values(ascending=False)


def select_holdings(held: set, ranked: list, top_n: int, buffer: int) -> list:
    """Monthly churn with a buffer band.
    ranked: eligible symbols, best first (rank 1 = best 3M return).
    1. Keep every current holding whose rank is within `buffer` (ranks 21-30 get time to
       come back); sell holdings ranked below `buffer` or no longer eligible/priced.
    2. Fill vacancies up to `top_n` with the best-ranked stocks not already held.
    First month (nothing held) = plain top_n. Never holds more than top_n."""
    rank = {s: i + 1 for i, s in enumerate(ranked)}
    keep = [s for s in held if rank.get(s, 10**9) <= buffer]
    keep.sort(key=rank.get)
    keep = keep[:top_n]
    for s in ranked:
        if len(keep) >= top_n:
            break
        if s not in keep:
            keep.append(s)
    return keep


def run(px: pd.DataFrame, to: pd.DataFrame, cfg: Cfg):
    """Run the monthly momentum backtest; return daily net/gross/benchmark returns and positions."""
    px_f, sig, adtv, vol = signals(px, to, cfg)
    ret = px_f.pct_change(fill_method=None)

    reb = month_ends(px.index)
    w = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    held: set = set()
    for d in reb:
        s = ranked_eligible(d, sig, adtv, px, vol, cfg)
        if len(s) < cfg.buffer:
            continue
        held = set(select_holdings(held, list(s.index), cfg.top_n, cfg.buffer))
        w.loc[d] = 0.0
        w.loc[d, list(held)] = 1.0 / len(held)  # equal weight, reset each month-end
    pos = w.ffill().fillna(0.0).shift(1).fillna(0.0)  # trade the day after signal

    gross = (pos * ret.fillna(0.0)).sum(axis=1)
    turn = pos.diff().abs().sum(axis=1).fillna(0.0)
    net = gross - turn * cfg.cost_bps / 1e4
    bench = ret.mean(axis=1)  # equal-weight universe, daily rebalanced

    out = pd.DataFrame({"net": net, "gross": gross, "bench": bench, "turnover": turn})
    invested = pos.abs().sum(axis=1) > 0
    first = invested.idxmax() if invested.any() else out.index[0]  # first day with a position
    out = out.loc[max(pd.Timestamp(cfg.start), first):cfg.end]
    out.insert(3, "buy_hold", buy_and_hold(px, out.index))
    return out, pos


def buy_and_hold(px: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.Series:
    """Daily returns of: split capital equally across every stock priced on the close before
    idx[0], then never trade again (weights drift, no costs). A stock that stops trading keeps
    its last price (value frozen, as if held in cash)."""
    pos = px.index.get_loc(idx[0])
    base = px.index[max(pos - 1, 0)]
    pf = px.ffill()
    cols = pf.columns[pf.loc[base].notna()]
    value = (pf.loc[base:, cols] / pf.loc[base, cols]).mean(axis=1)
    return value.pct_change().reindex(idx)


def stats(r: pd.Series, ann: int = 252) -> dict:
    """CAGR, annualised volatility, Sharpe (rf=0) and max drawdown of a daily return series."""
    r = r.dropna()
    eq = (1 + r).cumprod()
    vol = r.std() * np.sqrt(ann)
    return {
        "CAGR": float(eq.iloc[-1] ** (ann / len(r)) - 1),
        "Vol": float(vol),
        "Sharpe(rf=0)": float(r.mean() * ann / vol) if vol else float("nan"),
        "MaxDD": float((eq / eq.cummax() - 1).min()),
    }


def stats_row(r: pd.Series) -> dict:
    """stats() rounded for result tables (percentages x100), plus what Rs 1 cr becomes."""
    s = stats(r)
    return {"CAGR_%": round(s["CAGR"] * 100, 1), "Vol_%": round(s["Vol"] * 100, 1),
            "Sharpe": round(s["Sharpe(rf=0)"], 2), "MaxDD_%": round(s["MaxDD"] * 100, 1),
            "1cr_becomes_cr": round(float((1 + r.fillna(0.0)).prod()), 2)}


def add_trade_pnl(td: pd.DataFrame, cost_bps: float, last_date) -> pd.DataFrame:
    """Add gross/net P&L % (cost charged on entry and exit) and holding days; open trades run to last_date."""
    c = cost_bps / 1e4
    td["gross_pnl_pct"] = (td["exit_price"] / td["entry_price"] - 1) * 100
    td["net_pnl_pct"] = (td["exit_price"] * (1 - c) / (td["entry_price"] * (1 + c)) - 1) * 100
    end = pd.to_datetime(td["sell_date"]).fillna(last_date)
    td["holding_days"] = (end - pd.to_datetime(td["buy_date"])).dt.days
    td[["gross_pnl_pct", "net_pnl_pct"]] = td[["gross_pnl_pct", "net_pnl_pct"]].round(2)
    return td


RET_COLS = {"net": "strategy_net", "gross": "strategy_gross",
            "buy_hold": "buy_and_hold", "bench": "benchmark_equal_weight"}


def year_end_values(out: pd.DataFrame, capital_cr: float = 1.0) -> pd.DataFrame:
    """Value (INR crore) of `capital_cr` invested at the start, at each year-end and the last day."""
    eq = (1 + out[list(RET_COLS)].fillna(0.0)).cumprod() * capital_cr
    return eq.groupby(eq.index.year).last().rename(columns=RET_COLS)


def report(out: pd.DataFrame, cfg: Cfg) -> dict:
    """Summary dict (config, period, stats per return series, Rs 1 cr outcome, turnover) for JSON."""
    final = year_end_values(out).iloc[-1]
    return {
        "config": asdict(cfg),
        "period": {"start": str(out.index[0].date()), "end": str(out.index[-1].date()),
                   "years": round(len(out) / 252, 2)},
        **{name: stats(out[col]) for col, name in RET_COLS.items()},
        "rs_1cr_becomes_cr": {k: round(float(v), 2) for k, v in final.items()},
        "avg_annual_turnover_x": float(out["turnover"].mean() * 252),
    }
