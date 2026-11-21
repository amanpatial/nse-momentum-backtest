# nse-momentum-backtest

Monthly cross-sectional momentum on Indian stocks (Nifty 500 universe): rank by 3-month return, hold the
top 20, keep holdings until they drop below rank 30. Includes trade logs, a Zerodha cost model, and the
experiments tried so far (stop-loss, lookback / review frequency, volatility filter), each reproducible
with one command.

**Results at a glance** (Option A data, 2021-10-01 to 2026-06-09, before tax):

| | CAGR | Sharpe | Max DD | Rs 1 cr becomes |
|---|---|---|---|---|
| Base strategy @ 40 bps/side (default) | 28.9% | 1.09 | -31.0% | 3.21 cr |
| Base strategy @ 12 bps/side (Zerodha charges only) | 33.2% | 1.22 | -29.3% | 3.72 cr |
| + volatility filter, drop top 10% (12 bps) | 42.5% | 1.67 | -25.6% | 5.08 cr |
| Buy and hold, same universe | 28.3% | 1.36 | -24.4% | 3.14 cr |

All figures carry survivorship bias and cover a short, mostly bullish period; see [Limitations](#limitations).

---

## 1. Setup for a new developer

**Requirements:** Python 3.9 or newer, about 200 MB disk, macOS / Linux / Windows.

```bash
git clone <repo-url> nse-momentum-backtest && cd nse-momentum-backtest
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
python -m pytest tests/        # no data needed; all 9 tests should pass
```

**Get the data** (not in the repo, 54 MB): download `nifty500_5yr_data.csv` from the
[IITKGP Nifty500 dataset](https://huggingface.co/datasets/IITKGP/Nifty500_companies_5_years_data)
("Files and versions" tab) and put it in the `data/` folder (`data/nifty500_5yr_data.csv`).

**Build the database and reproduce every result in this README** (about a minute or less):
```bash
./run_all.sh                      # Windows: run the commands inside run_all.sh one by one
SKIP_BUILD=1 ./run_all.sh         # reuse an existing data/smallcap.duckdb
```
Expected check: `results/summary.json` shows `strategy_net.CAGR` = 0.2893.

**Open the dashboard (frontend)** to explore the results visually (details in [Dashboard](#dashboard)):
```bash
.venv/bin/streamlit run dashboard.py   # Windows: .venv\Scripts\streamlit run dashboard.py
```
Your browser opens at http://localhost:8501. Press `Ctrl+C` in the terminal to stop it.

Notes:
- On macOS system Python you may see a `NotOpenSSLWarning` from urllib3. It's harmless; `run_all.sh`
  hides it with `PYTHONWARNINGS=ignore`.
- Not in git (see `.gitignore`): `.venv/`, everything in `data/` except `corp_actions.csv` (the price CSV and
  `smallcap.duckdb`), and `results/`. All of it is downloaded or regenerated.
- Default file locations are defined once in `paths.py`, so scripts work from any folder.
- Code must stay Python 3.9 compatible: modules using `X | None` hints need `from __future__ import annotations`.

### Dashboard

A visual view of the same results, in addition to the command line (Streamlit + Plotly, both in
`requirements.txt`).

**Run it:**
1. Make sure results exist: `./run_all.sh` (or `SKIP_BUILD=1 ./run_all.sh` if `data/smallcap.duckdb` is already built).
2. From the repo root, start the app:
   ```bash
   .venv/bin/streamlit run dashboard.py                      # macOS / Linux
   .venv\Scripts\streamlit run dashboard.py                  # Windows
   # or, with the venv activated:  streamlit run dashboard.py
   ```
3. The browser opens at http://localhost:8501 (open it by hand if it doesn't).
4. Stop with `Ctrl+C` in that terminal. After rerunning `./run_all.sh`, just refresh the page.

Options:
```bash
.venv/bin/streamlit run dashboard.py --server.port 8600       # use another port if 8501 is busy
.venv/bin/streamlit run dashboard.py --server.headless true   # don't auto-open a browser (e.g. on a server)
```

Troubleshooting:
- *"Some results are missing"* on a page: run `./run_all.sh` first.
- *"data/smallcap.duckdb not found"* on **Run a backtest**: build the database with `./run_all.sh`.
- `ModuleNotFoundError: streamlit` / `plotly`: run `pip install -r requirements.txt` inside `.venv`.
- A "install the Watchdog module" tip in the terminal is optional (only speeds up reloads after code edits).

**Pages:**
- **Overview:** headline numbers, growth of Rs 1 cr, drawdowns, monthly-return heatmap, yearly returns
  (base strategy @ 40 bps or volatility filter @ 12 bps).
- **Trades:** filter any trade log by stock, exit reason and date; P&L distribution, holding period vs
  return, best/worst stocks; download the filtered CSV.
- **Experiments:** costs, volatility-filter heatmap, stop-loss, lookback / review-frequency variants.
- **Run a backtest:** change lookback, portfolio size, buffer, cost, liquidity and volatility filter, and
  rerun `backtest.run()` on `data/smallcap.duckdb` (a few seconds), compared with the default rules.

The dashboard only reads `results/` and the database; it never changes them. Follows your light/dark theme.

## 2. Project layout

```
backtest.py, ingest.py, paths.py      core modules (strategy engine, data loading, file locations)
pipeline.py, export_trades.py, ...    command-line scripts (table below)
dashboard.py                          Streamlit dashboard
run_all.sh                            reproduces every result
data/                                 inputs + database (only corp_actions.csv is in git; see data/README.md)
tests/                                pytest tests (no data needed)
results/                              outputs of run_all.sh (not in git)
```

| File | What it does |
|---|---|
| `paths.py` | Default file locations (`data/...`, `results/`), relative to the repo root |
| `pipeline.py` | CLI: `build-csv` / `build` the database, `check` data, run the main `backtest` |
| `ingest.py` | Data loading, NSE bhavcopy fetch, corporate-action adjustment, data checks |
| `universe.py` | Universe selection by market-cap rank (Option B) |
| `nifty500_downloader.py` | Optional: download ~10 years of Nifty 500 prices from Yahoo Finance into the CSV format `build-csv` reads (needs `pip install yfinance`; not used by `run_all.sh`) |
| `backtest.py` | Strategy rules, volatility filter, benchmarks, stats; shared helpers (`signals`, `month_ends`, `stats_row`, `add_trade_pnl`) used by every other engine |
| `costs.py` | Zerodha delivery charges calculator (justifies `--cost-bps`) |
| `export_trades.py` | Trade log of the main backtest (one row per buy -> sell) |
| `stoploss_backtest.py` | Share-based engine (weights drift between reviews); optional fixed stop-loss |
| `variants.py` | Lookback (3M/6M/12M) x review frequency (month-end/30d/45d) comparison |
| `sweep.py` | Parameter sweeps: cost levels, volatility-filter grid |
| `run_all.sh` | Rebuilds the database and regenerates every result |
| `dashboard.py` | Interactive web dashboard over `results/` (see [Dashboard](#dashboard)) |
| `data/corp_actions.csv` | Reviewed split / bonus / demerger adjustments used for the Option A build |
| `tests/test_rules.py` | Selection rule (buffer band) and volatility filter |
| `tests/test_csv_loader.py` | Single-CSV loader: split detection and adjustment, ticker cleanup |
| `tests/test_synthetic_pipeline.py` | End-to-end on synthetic NSE files: parse, rename, adjust, build, backtest |

## 3. Strategy rules (`backtest.py`)

- **Signal:** trailing 3-month return (63 trading days) on adjusted close. No skip month.
- **Eligible:** priced on the review date, with 20-day average traded value >= Rs 0.5 cr.
- **Volatility filter (optional, off by default):** see [section 6.5](#65-volatility-filter).
- **Portfolio:** top 20, equal weight (5% each).
- **Review:** last trading day of each month.
- **Buffer:** a holding is kept while its rank is 1-30; sold only when rank > 30 (or no longer eligible).
  A new top-20 stock waits for a free slot.
- **Vacancies** are filled from the best-ranked stocks not already held.
- **Timing:** ranked on the review-day close; positions earn returns from the next trading day (no
  lookahead). Fill price = review-day close (mildly optimistic).
- **Reinvestment:** profits and losses are fully reinvested (weights are % of current equity, returns
  compound). Always 100% invested. Fractional shares.
- **Weights:** `backtest.py` holds exactly 5% every day (daily rebalancing, costs charged only at
  reviews). `stoploss_backtest.py` / `variants.py` hold real shares that drift between reviews; their
  no-stop baseline gives almost the same result (33.3% vs 33.2% CAGR at 12 bps).
- **Costs:** `--cost-bps` per side, charged on every rupee bought or sold. Default 40.

**Benchmarks** (in every main backtest output):
- **Buy and hold:** Rs 1 cr split equally across every stock priced at the start, never traded again, no costs.
- **Equal weight:** average daily return of all stocks (rebalanced daily, no costs).

## 4. Data

### Option A: IITKGP Nifty 500 CSV (Jun 2021 - Jun 2026), used for all results here
```bash
python pipeline.py build-csv --corp-actions data/corp_actions.csv   # reads data/nifty500_5yr_data.csv
python pipeline.py check                                           # lists remaining >30% daily moves
```
The CSV prices are **not** adjusted for splits, bonuses or demergers. How `data/corp_actions.csv` was made:
1. A plain `build-csv` writes `data/detected_actions.csv`: 12 suspected unadjusted splits (big overnight drop
   on high volume).
2. Each was checked against price and volume. ABFRL, CGCL, GPIL and TRENT were real corporate actions.
   The others (ADANIENT, CYIENT, INDUSINDBK, PFC, RBLBANK, RECLTD, ZEEL, all ~25% drops) were treated as
   genuine price falls, not splits.
3. `check` found three more that weren't flagged: MOTILALOFS, VEDL and TMPV.
4. Those 7 went into `data/corp_actions.csv`.

`--auto-adjust` applies every flagged row blindly (it writes `data/detected_actions.csv.apply.csv`). Don't use
it for these results; it wrongly "adjusts" the genuine price falls.

`corp_actions.csv` format: `symbol,ex_date,factor`. The factor multiplies prices **before** `ex_date`:
5-for-1 split = 0.2, 1:1 bonus = 0.5.

Optional: `--universe data/universe.csv` (column `symbol`) restricts to a subset, e.g. the lower half of the 500
by traded value, to approximate small caps.

### Option B: NSE bhavcopy 2015 to date (needs access to nsearchives.nseindia.com; not tested live)
```bash
python pipeline.py universe --constituents nifty500_2016.csv      # ranks 251-600 -> data/universe.csv
python pipeline.py fetch --start 2015-01-01 --end 2026-11-20      # -> data/raw/
python pipeline.py build --universe data/universe.csv \
       --corp-actions data/corp_actions.csv --symbol-map symbol_map.csv
python pipeline.py check
```
Input files: `nifty500_2016.csv` (`symbol,mcap_cr`), `data/corp_actions.csv`, `symbol_map.csv` (`old,new`).

## 5. Command reference

**Main backtest:**
```bash
python pipeline.py backtest --out results/ [options]       # --db defaults to data/smallcap.duckdb
```

| Option | Default | Meaning |
|---|---|---|
| `--lookback` | 63 | Momentum lookback, trading days (126 = 6M, 252 = 12M) |
| `--skip` | 0 | Skip the most recent N days in the signal |
| `--top-n` | 20 | Portfolio size |
| `--buffer` | 30 | Holdings are sold only below this rank |
| `--min-adtv-cr` | 0.5 | Min 20-day average traded value, Rs crore |
| `--adtv-window` | 20 | Days for average traded value |
| `--cost-bps` | 40 | Cost per side, basis points |
| `--max-vol-pctile` | 1.0 | Volatility filter; 0.9 = drop the 10% most volatile, 1.0 = off |
| `--vol-window` | 63 | Trading days for volatility |
| `--vol-freq` | daily | `daily` or `weekly` returns for volatility |
| `--start` / `--end` | 2016-04-01 / none | Date range (first review is when data allows) |

Outputs in `--out`:
- `summary.json`: period; CAGR, vol, Sharpe, max drawdown for strategy (net and gross), buy and hold,
  equal weight; what Rs 1 cr becomes in each case; annual turnover.
- `daily_returns.csv`: daily `net`, `gross`, `bench`, `buy_hold` returns and `turnover`.
- `year_end_value_per_1cr.csv`: value of Rs 1 cr at each year-end for each approach.

**Other scripts** (all take `--db` (default `data/smallcap.duckdb`), `--cost-bps` (default 12), `--out`, and the three volatility options):

| Command | Extra options | Output |
|---|---|---|
| `python export_trades.py` | | trade log CSV |
| `python stoploss_backtest.py` | `--stops 0 0.20 0.25` | `results/stoploss/` |
| `python variants.py` | | `results/variants/` |
| `python sweep.py costs` | `--costs 12 20 40` | `results/sweeps/costs.csv` |
| `python sweep.py volfilter` | `--pctiles ... --windows ... --freqs ...` | `results/sweeps/volfilter.csv` |
| `python costs.py` | `--order 500000 --slippage-bps 9` | printed breakdown |

## 6. Experiment log

All at 12 bps per side unless stated. Each section gives the exact command to reproduce it.

### 6.1 Costs: what to use for `--cost-bps`
```bash
python costs.py --order 500000 --slippage-bps 9
python sweep.py costs --costs 12 20 40
```
Zerodha delivery charges (zerodha.com/charges, checked 2026-11-21; update `RATES` in `costs.py` if they change):

| Charge | Rate | Side |
|---|---|---|
| Brokerage | Rs 0 | - |
| STT | 0.1% | Buy and sell |
| Stamp duty | 0.015% | Buy |
| NSE transaction charge | 0.00307% | Both |
| SEBI fee | Rs 10 per crore | Both |
| GST | 18% on transaction charge + SEBI fee | Both |
| DP charge | Rs 15.34 per stock sold | Sell |

- On a Rs 5 lakh order (5% of Rs 1 cr): buy Rs 594 (0.119%), sell Rs 534 (0.107%), round trip 0.226%.
  That's about **11 bps per side**.
- STT is Rs 1,000 of the Rs 1,128 and applies on every broker.
- The 0.002% figure in the Zerodha calculator is only the NSE transaction-charge line, not the total.
- Slippage vs the close is extra: about 5-10 bps for Nifty 500 stocks with Rs 5 L orders, 20-30 bps or
  more for real small caps or larger capital.

| `--cost-bps` | Meaning | CAGR | Sharpe | Max DD | Rs 1 cr becomes | Cost drag/yr |
|---|---|---|---|---|---|---|
| 12 | Zerodha charges only (best case) | 33.2% | 1.22 | -29.3% | 3.72 cr | 1.4% |
| 20 | Zerodha + ~9 bps slippage (recommended for Nifty 500) | 31.9% | 1.18 | -29.8% | 3.57 cr | 2.3% |
| 40 | Default (cautious, closer to real small caps) | 28.9% | 1.09 | -31.0% | 3.21 cr | 4.6% |
| - | Buy and hold, no costs | 28.3% | 1.36 | -24.4% | 3.14 cr | - |
| - | Equal-weight benchmark, no costs | 25.0% | 1.35 | -21.2% | 2.78 cr | - |

Value of Rs 1 cr at each year-end (40 bps): see `results/year_end_value_per_1cr.csv`. Momentum built its
lead in 2022-2024 (3.39 cr vs 2.96 cr for buy and hold at end-2024) and lost most of it in 2025.

**Tax is not modelled.** Turnover is about 11.6x a year, so almost all strategy gains are short-term (STCG
20%, paid every year). Buy and hold pays LTCG 12.5% only at exit. After tax, buy and hold likely wins
against the base strategy.

### 6.2 Trade log
```bash
python export_trades.py --cost-bps 12 --out results/trades.csv
python export_trades.py --cost-bps 12 --max-vol-pctile 0.9 --out results/trades_volfilter90.csv
```
Columns: `symbol, ranking_date, entry_rank, entry_3m_return_pct, buy_date, entry_price, exit_rank_date,
exit_rank, exit_reason, sell_date, exit_price, holding_days, gross_pnl_pct, net_pnl_pct`.
- Prices are adjusted closes on the ranking date; `buy_date`/`sell_date` are the next trading day.
- `exit_reason`: `rank > 30`, `ineligible (illiquid / unpriced / too volatile)`, or `OPEN` (marked at the last date).
- Trade P&L won't add up exactly to portfolio return (`backtest.py` holds fixed 5% weights daily).

| | Base | Vol filter 0.9 |
|---|---|---|
| Trades (closed) | 541 (521) | 647 (627) |
| Win rate | 51.6% | 55.2% |
| Avg net P&L (median) | +5.3% (+0.6%) | +5.6% (+1.4%) |
| Avg win / avg loss | +20.3% / -10.8% | +17.0% / -8.5% |
| Avg hold | 64 days | 54 days |

The edge comes from a few big winners (base best: JINDALSAW +183%, PGEL +157%, SUZLON +149%), not a high hit rate.

### 6.3 Stop-loss (rejected)
```bash
python stoploss_backtest.py --cost-bps 12 --stops 0 0.20 0.25 --out results/stoploss
```
- **Exit** when the day's low touches entry price x (1 - stop). Fill at the stop, or at the open if it gaps below.
- **Cash** from a stop stays idle until the next month-end review.
- **Re-entry:** a stopped stock can be bought again at a later review under the base rule (top 20, free slot).
- **Holdings** are real shares that drift between reviews; each review resets to equal weight.

| | No stop | 20% stop | 25% stop |
|---|---|---|---|
| CAGR | **33.3%** | 29.4% | 31.5% |
| Rs 1 cr becomes | **3.74 cr** | 3.27 cr | 3.51 cr |
| Sharpe | **1.21** | 1.14 | 1.18 |
| Max DD | -29.7% | **-27.7%** | -29.5% |
| Stop exits (gap fills) | - | 88 (13) | 41 (5) |
| Worst trade | -45.1% | **-26.4%** | -28.9% |
| Stop saved money / cost money | - | 34 / 48 | 11 / 30 |
| Avg stopped trade vs same trade with no stop | - | -20.4% vs -15.1% | -25.4% vs -21.8% |
| Stopped stocks bought back later | - | 46 | 22 |

**Conclusion:** stops hurt.
- Most stopped stocks recovered.
- The rank > 30 rule already exits stocks that keep falling.
- Stop cash sits idle until the next review.
- The only benefit is a smaller worst trade.

Output: `summary.csv` (includes the saved/cost analysis), `trades_<variant>.csv` (with `stop_price`,
`stop_fill`), `daily_returns.csv`, `year_end_value_per_1cr.csv`.

### 6.4 Lookback and review frequency
```bash
python variants.py --cost-bps 12 --out results/variants
```
- **Lookback:** 3M = 63, 6M = 126, 12M = 252 trading days.
- **Review:** every 30 or 45 calendar days (first trading day on/after).
- **Common start:** all variants start 2022-06-14 (first 12M signal), so the 3M month-end base shows 35.2% here.
- **Robustness check:** each N-day variant is rerun with its schedule shifted by N/3 and 2N/3 days.

| Variant | CAGR | Sharpe | Max DD | Rs 1 cr becomes | Avg hold | Turnover/yr | CAGR, shifted schedules |
|---|---|---|---|---|---|---|---|
| 3M month-end (base) | 35.2% | 1.31 | -29.7% | 3.19 cr | 63 d | 12.2x | - |
| 3M 30d | 39.8% | 1.43 | -29.7% | 3.69 cr | 66 d | 11.6x | 39.0-41.0% |
| 3M 45d | 48.0% | 1.63 | -24.4% | 4.61 cr | 77 d | 10.0x | 39.7-48.0% |
| 6M 30d | 38.1% | 1.36 | -29.5% | 3.52 cr | 97 d | 8.0x | 38.1-41.6% |
| 6M 45d | 44.4% | 1.54 | -26.1% | 4.19 cr | 112 d | 6.9x | 39.4-45.2% |
| 12M 30d | 39.0% | 1.40 | -34.6% | 3.61 cr | 146 d | 5.6x | 39.0-45.2% |
| 12M 45d | 46.8% | 1.61 | -32.5% | 4.46 cr | 161 d | 5.1x | 41.0-46.8% |
| Equal-weight benchmark | 31.6% | 1.71 | -21.2% | 2.92 cr | - | - | - |

**Conclusion:** no clear winner.
- Gaps between variants are about the same size as the effect of just shifting review dates.
- Robust finding: longer lookbacks trade far less (12M about 5x vs 3M about 12x turnover).
- 6M 45d is the most balanced.
- No variant beats the equal-weight benchmark on Sharpe or drawdown.

### 6.5 Volatility filter
On each review date, compute each stock's trailing annualised volatility over the last `--vol-window`
trading days (default 63, about 3 months):
- `--vol-freq daily` (default): std of the daily returns x sqrt(252).
- `--vol-freq weekly`: std of 5-trading-day returns x sqrt(52), using non-overlapping weeks that end on the
  review date (63 days -> 13 weeks, 126 -> 26). Smooths out single-day spikes such as circuit days.

Among the liquid stocks, drop those above the `--max-vol-pctile` percentile (0.9 = drop the 10% most
volatile), then rank the rest. A stock needs 80% of the window's data. A holding that fails the filter is
no longer eligible and is sold, like an illiquid one.

```bash
python pipeline.py backtest --out results/volfilter --cost-bps 12 --max-vol-pctile 0.9     # single run
python sweep.py volfilter --cost-bps 12                                                     # full grid
```

Full grid, all settings on the same period, 2021-12-01 to 2026-06-09 (126-day windows need 2 more months
of history). CAGR / Sharpe / Max DD; filter off = 33.3% / 1.22 / -29.3%:

| Drop most volatile | Daily, 63d | Daily, 126d | Weekly, 13 wk | Weekly, 26 wk |
|---|---|---|---|---|
| 5% | 39.1% / 1.46 / -27.8% | 38.5% / 1.42 / -26.8% | 38.2% / 1.41 / -27.9% | 40.3% / 1.44 / -27.4% |
| 10% | **42.2% / 1.65 / -25.6%** | 37.0% / 1.43 / -23.3% | 33.8% / 1.35 / -24.1% | 33.1% / 1.30 / -24.7% |
| 15% | 34.5% / 1.48 / -25.8% | 39.7% / 1.56 / -26.2% | 38.7% / 1.58 / **-20.7%** | 33.6% / 1.37 / -22.2% |
| 20% | 29.2% / 1.37 / -23.6% | 30.6% / 1.33 / -23.4% | 29.5% / 1.31 / -22.7% | 30.3% / 1.32 / -20.5% |
| 30% | 28.1% / 1.39 / -20.1% | 30.4% / 1.44 / -21.1% | 29.2% / 1.40 / -21.5% | 25.7% / 1.25 / -21.6% |
| 50% | 19.6% / 1.16 / -19.7% | 25.8% / 1.41 / -16.6% | 24.3% / 1.36 / -18.8% | 25.5% / 1.39 / -18.0% |

On its own full period (from 2021-10-01), daily 63d with 10% dropped gives 42.5% CAGR, Rs 1 cr -> 5.08 cr.
At 40 bps it gives 37.1% (vs 28.9% base).

**Conclusion:** dropping the 5-15% most volatile helps.
- Every 5-15% setting beats the base on CAGR, Sharpe and drawdown, with both windows and both frequencies.
- Dropping more cuts risk further but gives up return.
- Results jump between neighbouring settings (sample noise). Expect about 35-40%, not the 42% peak.
- Weekly is not better than daily.
- Turnover rises (about 14x vs 12x) because holdings that become too volatile are sold.
- The share-based engine agrees (`stoploss_backtest.py --stops 0 --max-vol-pctile 0.9`: 41.8%).
- Still off by default; recommended setting: `--max-vol-pctile 0.9 --vol-window 63 --vol-freq daily`.

### 6.6 Ideas not yet tested
- Capital gains tax (STCG 20% on realized strategy gains each year, LTCG 12.5% on buy and hold at exit).
- Trailing stop-loss; market filter (go to cash when the index is below its 200-day average).
- Next-day open fills instead of ranking-day close.

## Limitations
- Option A universe is today's Nifty 500, so stocks that dropped out are missing (survivorship bias flatters results).
- Short sample (~4.6 years, mostly a bull market).
- Fills at the ranking-day close; capital gains tax not modelled; flat cost for every stock and trade size.
- Delisted stocks: returns after the last trading day count as 0 (optimistic).
- Benchmarks are equal-weight / buy-and-hold of the same universe, not Nifty Smallcap 250 TRI.
- Traded value in Option A is close x volume (proxy).
- Option B fetch URLs were not tested against live NSE; verify the legacy to UDiFF cutover (~8 Jul 2024).

## License

[MIT](LICENSE) © 2026 Aman Patial. Research code for educational use, not investment advice.
