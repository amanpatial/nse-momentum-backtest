"""Zerodha delivery (CNC) charges per trade, to justify the backtest's --cost-bps.

Usage: python costs.py --order 500000 --slippage-bps 9

Rates from zerodha.com/charges (equity delivery, NSE), checked 2026-11-21. Update RATES if they change.
STT is charged on both buy and sell for delivery trades on every broker, so it can't be avoided.
"""
import argparse

RATES = {
    "brokerage": 0.0,            # Rs 0 for delivery
    "stt": 0.001,                # 0.1% on buy and sell
    "stamp_buy": 0.00015,        # 0.015% on buy only
    "nse_txn": 0.0000307,        # 0.00307% on both sides
    "sebi": 10 / 1e7,            # Rs 10 per crore, both sides
    "gst": 0.18,                 # on brokerage + transaction charge + SEBI fee
    "dp_per_sell": 15.34,        # Rs per stock per sell day (flat)
}


def charges(value: float, side: str) -> dict:
    """Zerodha delivery charges in Rs for one buy or sell order of the given value."""
    r = RATES
    c = {"brokerage": value * r["brokerage"], "stt": value * r["stt"],
         "stamp": value * r["stamp_buy"] if side == "buy" else 0.0,
         "nse_txn": value * r["nse_txn"], "sebi": value * r["sebi"]}
    c["gst"] = r["gst"] * (c["brokerage"] + c["nse_txn"] + c["sebi"])
    c["dp"] = r["dp_per_sell"] if side == "sell" else 0.0
    c["total"] = sum(c.values())
    return c


def main():
    """CLI: print the per-side charge breakdown and the matching --cost-bps value."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", type=float, default=500000, help="order value in Rs (default: 5%% of Rs 1 cr)")
    ap.add_argument("--slippage-bps", type=float, default=9, help="assumed slippage per side vs the close")
    a = ap.parse_args()

    b, s = charges(a.order, "buy"), charges(a.order, "sell")
    print(f"Order value Rs {a.order:,.0f}\n")
    print(f"{'charge':<10}{'buy Rs':>10}{'sell Rs':>10}")
    for k in b:
        print(f"{k:<10}{b[k]:>10.2f}{s[k]:>10.2f}")
    per_side = (b["total"] + s["total"]) / 2 / a.order * 1e4
    print(f"\nbuy {b['total'] / a.order:.3%}  sell {s['total'] / a.order:.3%}  "
          f"round trip {(b['total'] + s['total']) / a.order:.3%}")
    print(f"statutory + broker cost per side: {per_side:.1f} bps")
    print(f"with {a.slippage_bps:g} bps slippage: --cost-bps {per_side + a.slippage_bps:.0f}")


if __name__ == "__main__":
    main()
