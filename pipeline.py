"""CLI: python pipeline.py <fetch|universe|build|check|backtest> ...

Typical run on a machine that can reach NSE:
  python pipeline.py universe --constituents nifty500_2016.csv --out universe.csv
  python pipeline.py fetch --start 2015-01-01 --end 2026-11-19 --out raw/
  python pipeline.py build --raw raw/ --db smallcap.duckdb --universe universe.csv \
        --corp-actions corp_actions.csv --symbol-map symbol_map.csv
  python pipeline.py check --db smallcap.duckdb
  python pipeline.py backtest --db smallcap.duckdb --out results/
"""
import argparse
import datetime as dt
import json
import pathlib

import backtest as bt
import data
import universe


def main():
    """CLI entry point: dispatch universe / fetch / build / check / backtest subcommands."""
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("universe")
    p.add_argument("--constituents", required=True)
    p.add_argument("--start-rank", type=int, default=251)
    p.add_argument("--end-rank", type=int, default=600)
    p.add_argument("--out", default="universe.csv")

    p = sub.add_parser("fetch")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", default="raw")

    p = sub.add_parser("build")
    p.add_argument("--raw", required=True)
    p.add_argument("--db", default="smallcap.duckdb")
    p.add_argument("--universe")
    p.add_argument("--corp-actions")
    p.add_argument("--symbol-map")
    p.add_argument("--parquet")

    p = sub.add_parser("build-csv")
    p.add_argument("--csv", required=True)
    p.add_argument("--db", default="smallcap.duckdb")
    p.add_argument("--auto-adjust", action="store_true")
    p.add_argument("--corp-actions")
    p.add_argument("--detected-out", default="detected_actions.csv")
    p.add_argument("--universe")

    p = sub.add_parser("check")
    p.add_argument("--db", default="smallcap.duckdb")

    p = sub.add_parser("backtest")
    p.add_argument("--db", default="smallcap.duckdb")
    p.add_argument("--out", default="results")
    for k, v in bt.Cfg().__dict__.items():
        if v is not None:
            p.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
    p.add_argument("--end", default=None)

    a = ap.parse_args()
    if a.cmd == "universe":
        sel = universe.select(a.constituents, a.start_rank, a.end_rank, a.out)
        print(f"{len(sel)} stocks -> {a.out}")
    elif a.cmd == "fetch":
        data.fetch(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), a.out)
    elif a.cmd == "build":
        print(data.build_db(a.raw, a.db, a.corp_actions, a.symbol_map, a.universe, a.parquet))
    elif a.cmd == "build-csv":
        n, k = data.build_db_from_csv(a.csv, a.db, a.auto_adjust, a.corp_actions, a.detected_out, a.universe)
        print(n, f"| {k} possible unadjusted splits flagged in {a.detected_out}")
    elif a.cmd == "check":
        for name, df in data.checks(a.db).items():
            print(f"\n== {name} ==\n{df.head(25).to_string(index=False)}")
    elif a.cmd == "backtest":
        cfg = bt.Cfg(**{k: getattr(a, k) for k in bt.Cfg().__dict__})
        px, to = bt.load_panel(a.db)
        out, _ = bt.run(px, to, cfg)
        res = bt.report(out, cfg)
        d = pathlib.Path(a.out)
        d.mkdir(parents=True, exist_ok=True)
        out.to_csv(d / "daily_returns.csv")
        bt.year_end_values(out).round(2).to_csv(d / "year_end_value_per_1cr.csv")
        (d / "summary.json").write_text(json.dumps(res, indent=2))
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
