"""CLI: python pipeline.py <download|universe|fetch|build|build-csv|check|backtest> ...

Default paths come from paths.py (inputs and the database in data/, outputs in results/).

Option A (single CSV, used for every result in the README), see run_all.sh:
  python pipeline.py download          # fetch + verify data/nifty500_5yr_data.csv (skips if present)
  python pipeline.py build-csv --csv data/nifty500_5yr_data.csv --corp-actions data/corp_actions.csv
  python pipeline.py check
  python pipeline.py backtest --out results/

Option B (NSE bhavcopies, on a machine that can reach NSE):
  python pipeline.py universe --constituents nifty500_2016.csv
  python pipeline.py fetch --start 2015-01-01 --end 2026-11-19
  python pipeline.py build --universe data/universe.csv --corp-actions data/corp_actions.csv \
        --symbol-map symbol_map.csv
"""
import argparse
import datetime as dt
import json
import pathlib

import backtest as bt
import ingest
import paths
import universe


def main():
    """CLI entry point: dispatch universe / fetch / build / check / backtest subcommands."""
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("download", help="download and verify the Option A price CSV")
    p.add_argument("--out", default=str(paths.PRICES_CSV))
    p.add_argument("--force", action="store_true", help="re-download even if a verified copy exists")

    p = sub.add_parser("universe")
    p.add_argument("--constituents", required=True)
    p.add_argument("--start-rank", type=int, default=251)
    p.add_argument("--end-rank", type=int, default=600)
    p.add_argument("--out", default=str(paths.UNIVERSE_CSV))

    p = sub.add_parser("fetch")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", default=str(paths.RAW_DIR))

    p = sub.add_parser("build")
    p.add_argument("--raw", default=str(paths.RAW_DIR))
    p.add_argument("--db", default=str(paths.DB))
    p.add_argument("--universe")
    p.add_argument("--corp-actions")
    p.add_argument("--symbol-map")
    p.add_argument("--parquet")

    p = sub.add_parser("build-csv")
    p.add_argument("--csv", default=str(paths.PRICES_CSV))
    p.add_argument("--db", default=str(paths.DB))
    p.add_argument("--auto-adjust", action="store_true")
    p.add_argument("--corp-actions")
    p.add_argument("--detected-out", default=str(paths.DETECTED_ACTIONS))
    p.add_argument("--universe")

    p = sub.add_parser("check")
    p.add_argument("--db", default=str(paths.DB))

    p = sub.add_parser("backtest")
    p.add_argument("--db", default=str(paths.DB))
    p.add_argument("--out", default=str(paths.RESULTS_DIR))
    for k, v in bt.Cfg().__dict__.items():
        if v is not None:
            p.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
    p.add_argument("--end", default=None)

    a = ap.parse_args()
    if a.cmd == "download":
        ingest.download_prices_csv(a.out, force=a.force)
    elif a.cmd == "universe":
        sel = universe.select(a.constituents, a.start_rank, a.end_rank, a.out)
        print(f"{len(sel)} stocks -> {a.out}")
    elif a.cmd == "fetch":
        ingest.fetch(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), a.out)
    elif a.cmd == "build":
        print(ingest.build_db(a.raw, a.db, a.corp_actions, a.symbol_map, a.universe, a.parquet))
    elif a.cmd == "build-csv":
        n, k = ingest.build_db_from_csv(a.csv, a.db, a.auto_adjust, a.corp_actions, a.detected_out, a.universe)
        print(n, f"| {k} possible unadjusted splits flagged in {a.detected_out}")
    elif a.cmd == "check":
        for name, df in ingest.checks(a.db).items():
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
