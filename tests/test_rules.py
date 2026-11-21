"""Unit tests for the buffer-band selection rule (top 20, sell only below rank 30) and the volatility filter.

Run: python -m pytest tests/   or   python tests/test_rules.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # import the repo-root modules

from backtest import select_holdings  # noqa: E402

N, B = 20, 30
universe = [f"S{i:02d}" for i in range(1, 61)]            # S01 = rank 1


def test_first_month_is_plain_top_n():
    """With nothing held yet, the portfolio is simply the top 20 by rank."""
    assert select_holdings(set(), universe, N, B) == universe[:20]


def test_holding_at_rank_21_to_30_is_kept():
    """A holding that slips to rank 21-30 (including exactly 30) is kept, not sold."""
    held = set(universe[:20])
    # S05 drops to rank 25, S01 to rank 30 (boundary), others shuffle up
    ranked = [s for s in universe if s not in ("S05", "S01")]
    ranked = ranked[:24] + ["S05"] + ranked[24:28] + ["S01"] + ranked[28:]
    r = {s: i + 1 for i, s in enumerate(ranked)}
    assert r["S05"] == 25 and r["S01"] == 30
    out = select_holdings(held, ranked, N, B)
    assert "S05" in out and "S01" in out                    # kept, no forced sell
    assert len(out) == N and len(set(out)) == N


def test_holding_below_30_is_sold_and_replaced_by_best_non_held():
    """A holding that falls below rank 30 is sold and its slot goes to the best stock not held."""
    held = set(universe[:20])
    ranked = [s for s in universe if s != "S03"]
    ranked = ranked[:30] + ["S03"] + ranked[30:]            # S03 now rank 31
    out = select_holdings(held, ranked, N, B)
    assert "S03" not in out
    assert "S21" in out or ranked[20] in out                # best non-held fills the gap
    assert len(out) == N


def test_new_top20_entrant_waits_for_a_vacancy():
    """A new top-20 stock is not bought while all 20 holdings are still within rank 30."""
    held = set(universe[:20])
    ranked = ["S40"] + [s for s in universe if s != "S40"]  # S40 jumps to rank 1
    out = select_holdings(held, ranked, N, B)               # all 20 held still within 30
    assert "S40" not in out and set(out) == held


def test_unpriced_or_ineligible_holding_is_sold():
    """A holding missing from the ranked list (unpriced/illiquid/filtered) is sold and replaced."""
    held = set(universe[:20])
    ranked = [s for s in universe if s != "S10"]            # S10 missing/ineligible
    out = select_holdings(held, ranked, N, B)
    assert "S10" not in out and len(out) == N


def test_volatility_filter_drops_most_volatile():
    """Volatility filter removes the most volatile stocks and leaves the rest in signal order."""
    import pandas as pd
    from backtest import Cfg, ranked_eligible
    d = pd.Timestamp("2024-01-31")
    syms = [f"V{i}" for i in range(10)]
    one = lambda vals: pd.DataFrame([vals], index=[d], columns=syms)
    sig = one([0.9 - i * 0.1 for i in range(10)])           # V0 best signal
    adtv = one([1.0] * 10)
    px = one([100.0] * 10)
    vol = one([1.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.25])   # V0 is the most volatile
    off = ranked_eligible(d, sig, adtv, px, vol, Cfg(max_vol_pctile=1.0))
    assert list(off.index) == syms                          # filter off: pure signal order
    on = ranked_eligible(d, sig, adtv, px, vol, Cfg(max_vol_pctile=0.8))
    assert "V0" not in on and "V8" not in on                # top 20% by vol removed
    assert list(on.index) == [s for s in syms if s not in ("V0", "V8")]   # rest keep signal order


def test_weekly_volatility_matches_hand_calculation():
    """Weekly volatility equals a hand-computed 13-week std x sqrt(52), and is NaN until enough history."""
    import numpy as np
    import pandas as pd
    from backtest import Cfg, volatility
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-01", periods=120)
    px = pd.DataFrame({"A": 100 * np.cumprod(1 + rng.normal(0, 0.02, len(idx)))}, index=idx)
    v = volatility(px, Cfg(vol_window=63, vol_freq="weekly"))
    d = 100                                                  # check one date by hand
    a = px["A"].values
    weeks = [a[d - 5 * k] / a[d - 5 * k - 5] - 1 for k in range(13)]   # 13 weeks ending on day d
    assert abs(v["A"].iloc[d] - np.std(weeks, ddof=1) * np.sqrt(52)) < 1e-12
    assert v["A"].iloc[:50].isna().all()                     # not enough weeks yet
    daily = volatility(px, Cfg(vol_window=63, vol_freq="daily"))
    assert abs(v["A"].iloc[d] / daily["A"].iloc[d] - 1) < 0.6    # same order of magnitude


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
