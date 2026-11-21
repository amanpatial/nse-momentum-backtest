"""Interactive dashboard for the momentum backtest results.

Usage: streamlit run dashboard.py      (after ./run_all.sh has written results/)

Pages: Overview, Trades, Experiments (reads results/), and Run a backtest (reruns backtest.run on
smallcap.duckdb with your own settings). The command-line scripts are unchanged.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import backtest as bt

ROOT = pathlib.Path(__file__).resolve().parent
RES = ROOT / "results"
DB = ROOT / "smallcap.duckdb"

st.set_page_config(page_title="NSE Momentum Backtest", page_icon="📈", layout="wide")


# ---------------------------------------------------------------- theme & palette

def is_dark() -> bool:
    """True when the viewer's Streamlit theme is dark (falls back to light on older Streamlit)."""
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


DARK = is_dark()
# Validated categorical palette (fixed order, light / dark steps); see the dataviz reference palette.
SLOTS = (["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9"] if DARK else
         ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"])
INK = "#f0efec" if DARK else "#0b0b0b"
INK2 = "#c3c2b7" if DARK else "#52514e"
MUTED = "#898781"
GRID = "#2c2c2a" if DARK else "#e1e0d9"
AXIS = "#383835" if DARK else "#c3c2b7"
SURFACE = "#1a1a19" if DARK else "#fcfcfb"
GAIN, LOSS, MID = SLOTS[0], ("#e66767" if DARK else "#e34948"), ("#383835" if DARK else "#f0efec")
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

# Colour follows the entity, on every page.
ENTITY = {"Strategy (net)": SLOTS[0], "Strategy (gross)": SLOTS[0], "Buy & hold": SLOTS[1],
          "Equal-weight benchmark": MUTED}
DASH = {"Strategy (gross)": "dot", "Equal-weight benchmark": "dash"}
RET_NAMES = {"net": "Strategy (net)", "gross": "Strategy (gross)", "buy_hold": "Buy & hold",
             "bench": "Equal-weight benchmark"}


def style(fig: go.Figure, height: int = 380, ytitle: str = "", yfmt: str | None = None,
          log: bool = False, hover: str = "x unified") -> go.Figure:
    """Apply the shared chart look: thin hairline grid, recessive axes, legend on top, unified hover."""
    fig.update_layout(
        height=height, margin=dict(l=70, r=20, t=40, b=40), hovermode=hover,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK2, size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=INK2)),
        hoverlabel=dict(bgcolor=SURFACE, font_color=INK, bordercolor=AXIS),
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont_color=MUTED, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, gridwidth=1, linecolor=AXIS, tickfont_color=MUTED,
                     zeroline=False, title_text=ytitle, title_font_color=MUTED, automargin=True,
                     type="log" if log else "-", tickformat=yfmt)
    return fig


def show(fig: go.Figure):
    """Render a Plotly figure full width with our own styling (not Streamlit's chart theme)."""
    st.plotly_chart(fig, theme=None, config={"displaylogo": False})


def data_view(df: pd.DataFrame, label: str = "Show data"):
    """Collapsible table under a chart (the accessible view of the same numbers)."""
    with st.expander(label):
        st.dataframe(df, width="stretch")


# ---------------------------------------------------------------- loading

@st.cache_data
def read_csv(rel: str, mtime: float, **kw) -> pd.DataFrame:
    """Read a results CSV (mtime is only a cache key so reruns of run_all.sh are picked up)."""
    return pd.read_csv(RES / rel, **kw)


def load(rel: str, **kw) -> pd.DataFrame | None:
    """Load results/<rel> if it exists, else None."""
    p = RES / rel
    return read_csv(rel, p.stat().st_mtime, **kw) if p.exists() else None


def load_json(rel: str) -> dict | None:
    """Load results/<rel> JSON if it exists, else None."""
    p = RES / rel
    return json.loads(p.read_text()) if p.exists() else None


def need(*objs) -> bool:
    """Show a hint and return False if any required results file is missing."""
    if any(o is None for o in objs):
        st.warning("Some results are missing. Run `./run_all.sh` in the repo root first, then reload.")
        return False
    return True


def daily(rel: str) -> pd.DataFrame | None:
    """Daily returns CSV indexed by date."""
    df = load(rel, index_col=0, parse_dates=True)
    return None if df is None else df.sort_index()


def equity(r: pd.DataFrame) -> pd.DataFrame:
    """Value of Rs 1 cr over time from daily returns (NaN = not yet invested)."""
    return (1 + r.fillna(0.0)).cumprod().where(r.ffill().notna())


def drawdown(eq: pd.DataFrame) -> pd.DataFrame:
    """Drop from the running peak, as a fraction."""
    return eq / eq.cummax() - 1


# ---------------------------------------------------------------- shared charts

def growth_chart(eq: pd.DataFrame, colors: dict, dashes: dict | None = None, log: bool = False,
                 height: int = 420) -> go.Figure:
    """Growth of Rs 1 cr, one line per column; the final value is shown in the legend."""
    fig = go.Figure()
    for col in eq.columns:
        s = eq[col].dropna()
        fig.add_trace(go.Scatter(
            x=s.index, y=s, name=f"{col} · {s.iloc[-1]:.2f} cr", mode="lines",
            line=dict(color=colors.get(col, MUTED), width=2, dash=(dashes or {}).get(col, "solid")),
            hovertemplate="%{y:.2f} cr"))
    return style(fig, height, "Value of Rs 1 cr (crore)", log=log)


def drawdown_chart(dd: pd.DataFrame, colors: dict, height: int = 260) -> go.Figure:
    """Drawdown lines (0 = at a new high)."""
    fig = go.Figure()
    for col in dd.columns:
        s = dd[col].dropna()
        fig.add_trace(go.Scatter(x=s.index, y=s, name=f"{col} · worst {s.min():.1%}", mode="lines",
                                 line=dict(color=colors.get(col, MUTED), width=2),
                                 hovertemplate="%{y:.1%}"))
    return style(fig, height, "Drawdown", yfmt=".0%")


def monthly_heatmap(r: pd.Series) -> tuple[go.Figure, pd.DataFrame]:
    """Calendar heatmap of monthly returns (diverging: red loss, gray zero, blue gain)."""
    m = (1 + r.dropna()).groupby([r.dropna().index.year, r.dropna().index.month]).prod() - 1
    tbl = m.unstack()
    tbl.columns = [pd.Timestamp(2000, c, 1).strftime("%b") for c in tbl.columns]
    tbl["Year"] = (1 + tbl.fillna(0)).prod(axis=1) - 1
    z = tbl.drop(columns="Year")
    lim = float(np.nanmax(np.abs(z.values)))
    fig = go.Figure(go.Heatmap(
        z=z.values, x=z.columns, y=[str(y) for y in z.index], zmid=0, zmin=-lim, zmax=lim,
        colorscale=[[0, LOSS], [0.5, MID], [1, GAIN]], xgap=2, ygap=2,
        text=np.where(np.isnan(z.values), "", np.vectorize(lambda v: f"{v:+.1%}")(np.nan_to_num(z.values))),
        texttemplate="%{text}", textfont=dict(size=11, color=INK),
        hovertemplate="%{x} %{y}: %{z:+.2%}<extra></extra>", colorbar=dict(tickformat=".0%", thickness=10)))
    style(fig, 60 + 34 * len(z), hover="closest")
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)", type="category")
    return fig, (tbl * 100).round(1)


def stat_tiles(s: dict, ref: dict | None, one_cr: float, ref_cr: float | None, turnover: float | None = None,
               ref_label: str = "buy & hold"):
    """Headline tiles; deltas compare with the reference (buy & hold by default)."""
    cols = st.columns(5 if turnover is not None else 4)
    d = (lambda k, f: f(s[k] - ref[k])) if ref else (lambda k, f: None)
    cols[0].metric("CAGR", f"{s['CAGR']:.1%}", d("CAGR", lambda v: f"{v * 100:+.1f} pts vs {ref_label}"))
    cols[1].metric("Sharpe (rf = 0)", f"{s['Sharpe(rf=0)']:.2f}", d("Sharpe(rf=0)", lambda v: f"{v:+.2f}"))
    cols[2].metric("Max drawdown", f"{s['MaxDD']:.1%}", d("MaxDD", lambda v: f"{v * 100:+.1f} pts"))
    cols[3].metric("Rs 1 cr becomes", f"{one_cr:.2f} cr",
                   f"{one_cr - ref_cr:+.2f} cr" if ref_cr is not None else None)
    if turnover is not None:
        cols[4].metric("Annual turnover", f"{turnover:.1f}x")


# ---------------------------------------------------------------- pages

STRATS = {
    "Base strategy @ 40 bps/side": ("summary.json", "daily_returns.csv"),
    "Volatility filter (drop top 10%) @ 12 bps/side": ("volfilter/summary.json", "volfilter/daily_returns.csv"),
}


def page_overview():
    """Headline numbers, growth of Rs 1 cr, drawdowns and monthly returns for one strategy."""
    st.title("NSE momentum backtest")
    st.caption("Nifty 500 universe · rank by 3-month return, hold top 20, sell below rank 30 · "
               "before tax · survivorship-biased, short and mostly bullish period (see README, Limitations)")
    choice = st.radio("Strategy", list(STRATS), horizontal=True, label_visibility="collapsed")
    summ, r = load_json(STRATS[choice][0]), daily(STRATS[choice][1])
    if not need(summ, r):
        return
    p = summ["period"]
    st.caption(f"{p['start']} to {p['end']} ({p['years']} years) · cost {summ['config']['cost_bps']:g} bps "
               "per side · buy & hold has no costs")
    becomes = summ["rs_1cr_becomes_cr"]
    stat_tiles(summ["strategy_net"], summ["buy_and_hold"], becomes["strategy_net"], becomes["buy_and_hold"],
               summ["avg_annual_turnover_x"])

    eq = equity(r[list(RET_NAMES)]).rename(columns=RET_NAMES)
    st.subheader("Growth of Rs 1 crore")
    log = st.toggle("Log scale", value=False)
    show(growth_chart(eq, ENTITY, DASH, log=log))
    st.subheader("Drawdown")
    show(drawdown_chart(drawdown(eq[["Strategy (net)", "Buy & hold"]]), ENTITY))

    st.subheader("Monthly returns, strategy net")
    fig, tbl = monthly_heatmap(r["net"])
    show(fig)
    data_view(tbl, "Show monthly returns table (%)")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Calendar-year returns (%)")
        yearly = ((1 + r[list(RET_NAMES)].fillna(0)).groupby(r.index.year).prod() - 1).rename(columns=RET_NAMES)
        yearly.index.name = "Year"
        short = {"Strategy (net)": "Net", "Strategy (gross)": "Gross", "Equal-weight benchmark": "Equal-weight"}
        st.dataframe((yearly * 100).round(1).rename(columns=short), width="stretch")
        st.caption("First and last years are partial.")
    with c2:
        st.subheader("All statistics")
        rows = {RET_NAMES[k]: summ[v] for k, v in bt.RET_COLS.items()}
        stats_tbl = pd.DataFrame(rows).T
        stats_tbl[["CAGR", "Vol", "MaxDD"]] *= 100
        st.dataframe(stats_tbl.round(2).rename(columns={"CAGR": "CAGR %", "Vol": "Vol %", "MaxDD": "MaxDD %"}),
                     width="stretch")


TRADE_FILES = {
    "Base strategy @ 12 bps": "trades.csv",
    "Volatility filter (drop top 10%) @ 12 bps": "trades_volfilter90.csv",
    "Stop-loss 20% @ 12 bps": "stoploss/trades_stop_20.csv",
    "Stop-loss 25% @ 12 bps": "stoploss/trades_stop_25.csv",
}


def page_trades():
    """Filterable trade log with P&L distribution, holding-period scatter and per-stock totals."""
    st.title("Trades")
    st.caption("One row per holding period (buy → sell). P&L is net of costs. Open positions have no sell date.")
    for f in sorted((RES / "variants").glob("trades_*.csv")):
        TRADE_FILES.setdefault(f"Variant {f.stem.removeprefix('trades_')} @ 12 bps", f"variants/{f.name}")
    src = st.selectbox("Trade log", list(TRADE_FILES))
    td = load(TRADE_FILES[src], parse_dates=["buy_date", "sell_date"])
    if not need(td):
        return

    c1, c2, c3 = st.columns([2, 2, 3])
    syms = c1.multiselect("Stocks", sorted(td["symbol"].unique()), placeholder="All stocks")
    reasons = c2.multiselect("Exit reason", sorted(td["exit_reason"].dropna().unique()) + ["open"],
                             placeholder="All exits")
    lo, hi = td["buy_date"].min().date(), td["buy_date"].max().date()
    dates = c3.slider("Buy date", lo, hi, (lo, hi), format="YYYY-MM-DD")
    f = td[(td["buy_date"].dt.date >= dates[0]) & (td["buy_date"].dt.date <= dates[1])]
    if syms:
        f = f[f["symbol"].isin(syms)]
    if reasons:
        f = f[f["exit_reason"].fillna("open").isin(reasons)]
    closed = f[f["sell_date"].notna()]
    if closed.empty:
        st.info("No closed trades match these filters.")
        return

    wins, losses = closed[closed["net_pnl_pct"] > 0], closed[closed["net_pnl_pct"] <= 0]
    m = st.columns(6)
    m[0].metric("Closed trades", f"{len(closed)}", f"{len(f) - len(closed)} open", delta_color="off")
    m[1].metric("Win rate", f"{len(wins) / len(closed):.1%}")
    m[2].metric("Average net P&L", f"{closed['net_pnl_pct'].mean():+.2f}%",
                f"median {closed['net_pnl_pct'].median():+.2f}%", delta_color="off")
    m[3].metric("Average win", f"{wins['net_pnl_pct'].mean():+.1f}%" if len(wins) else "–")
    m[4].metric("Average loss", f"{losses['net_pnl_pct'].mean():+.1f}%" if len(losses) else "–")
    m[5].metric("Average holding", f"{closed['holding_days'].mean():.0f} days")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Distribution of net P&L per trade")
        fig = go.Figure()
        bins = dict(start=float(np.floor(closed["net_pnl_pct"].min() / 5) * 5), size=5)
        for name, d, col in (("Losses", losses, LOSS), ("Wins", wins, GAIN)):
            fig.add_trace(go.Histogram(x=d["net_pnl_pct"], name=f"{name} · {len(d)}", marker_color=col,
                                       xbins=bins, hovertemplate="%{x}%: %{y} trades<extra></extra>"))
        fig.update_layout(barmode="overlay", bargap=0.08)
        show(style(fig, 360, "Trades", hover="closest").update_xaxes(title_text="Net P&L %", ticksuffix="%"))
    with c2:
        st.subheader("Holding period vs return")
        fig = go.Figure()
        for name, d, col in (("Losses", losses, LOSS), ("Wins", wins, GAIN)):
            fig.add_trace(go.Scatter(
                x=d["holding_days"], y=d["net_pnl_pct"], mode="markers", name=name,
                marker=dict(color=col, size=8, opacity=0.75, line=dict(color=SURFACE, width=1)),
                customdata=d[["symbol", "buy_date"]].astype(str),
                hovertemplate="%{customdata[0]} (bought %{customdata[1]})<br>%{x} days, %{y:+.1f}%<extra></extra>"))
        show(style(fig, 360, "Net P&L %", hover="closest").update_xaxes(title_text="Holding days"))

    st.subheader("Total net P&L by stock (sum of trade %, top and bottom 12)")
    by = closed.groupby("symbol")["net_pnl_pct"].agg(["sum", "count"]).sort_values("sum")
    pick = pd.concat([by.head(12), by.tail(12)]).drop_duplicates() if len(by) > 24 else by
    fig = go.Figure(go.Bar(x=pick["sum"], y=pick.index, orientation="h",
                           marker_color=[GAIN if v > 0 else LOSS for v in pick["sum"]],
                           customdata=pick["count"], hovertemplate="%{y}: %{x:+.1f}% over %{customdata} trades<extra></extra>"))
    show(style(fig, max(300, 22 * len(pick)), hover="closest").update_xaxes(ticksuffix="%", showgrid=True, gridcolor=GRID))

    st.subheader("Trade log")
    st.dataframe(f, width="stretch", hide_index=True, column_config={
        "buy_date": st.column_config.DateColumn("buy_date"), "sell_date": st.column_config.DateColumn("sell_date"),
        "net_pnl_pct": st.column_config.NumberColumn("net_pnl_pct", format="%.2f%%"),
        "gross_pnl_pct": st.column_config.NumberColumn("gross_pnl_pct", format="%.2f%%")})
    st.download_button("Download filtered trades (CSV)", f.to_csv(index=False), "trades_filtered.csv")


def exp_costs():
    """Cost sensitivity: CAGR and Rs 1 cr outcome at each cost level vs the no-cost benchmarks."""
    df = load("sweeps/costs.csv")
    if not need(df):
        return
    st.caption("Same rules, different cost per side. Benchmarks are shown without costs.")
    colors = [SLOTS[0] if str(v).startswith("strategy") else
              (SLOTS[1] if "buy and hold" in v else MUTED) for v in df["variant"]]
    labels = [v.replace("strategy @ ", "Strategy @ ").replace("/side", "").replace(" (no costs)", "")
              .replace("buy and hold", "Buy & hold").replace("equal-weight benchmark", "Equal-weight") for v in df["variant"]]
    fig = go.Figure(go.Bar(x=labels, y=df["CAGR_%"], marker_color=colors, cliponaxis=False,
                           text=[f"{v:.1f}%" for v in df["CAGR_%"]], textposition="outside",
                           textfont_color=INK2, hovertemplate="%{x}: %{y:.1f}% CAGR<extra></extra>"))
    show(style(fig, 360, "CAGR %", hover="closest").update_layout(bargap=0.45)
         .update_yaxes(range=[0, df["CAGR_%"].max() * 1.15]).update_xaxes(tickangle=0))
    st.dataframe(df, width="stretch", hide_index=True)


def exp_volfilter():
    """Volatility-filter grid as a heatmap (window x share of most volatile stocks dropped)."""
    df = load("sweeps/volfilter.csv")
    if not need(df):
        return
    st.caption("Before ranking, drop the most volatile X% of liquid stocks. All settings are scored on the "
               "same common period, so the numbers differ slightly from the standalone run.")
    c1, c2 = st.columns(2)
    freq = c1.radio("Volatility from", ["daily", "weekly"], horizontal=True)
    metric = c2.radio("Metric", ["CAGR_%", "Sharpe", "MaxDD_%", "1cr_becomes_cr"], horizontal=True)
    off = df[df["vol_freq"] == "-"]
    sub = df[df["vol_freq"] == freq]
    rows = []
    for w in sorted(sub["vol_window"].astype(int).unique()):
        g = pd.concat([off.assign(vol_window=str(w)), sub[sub["vol_window"].astype(int) == w]])
        rows.append(g.set_index("drop_most_volatile_%")[metric].rename(f"{w}-day window"))
    grid = pd.DataFrame(rows)
    grid.columns = [f"drop {c}%" if c else "off" for c in grid.columns]
    fig = go.Figure(go.Heatmap(
        z=grid.values, x=grid.columns, y=grid.index, colorscale=[[i / 6, c] for i, c in enumerate(SEQ_BLUE)],
        xgap=2, ygap=2, text=grid.values, texttemplate="%{text}",
        textfont=dict(size=13), hovertemplate="%{y}, %{x}: %{z}<extra></extra>",
        colorbar=dict(thickness=10, title=dict(text=metric, font_color=MUTED))))
    style(fig, 260, hover="closest").update_yaxes(gridcolor="rgba(0,0,0,0)", type="category")
    show(fig)
    st.caption("Darker = higher value. For MaxDD, higher (less negative) is better.")
    data_view(df, "Show full grid")


def exp_stoploss():
    """Stop-loss comparison: growth curves and how often stops helped vs hurt."""
    summ, r = load("stoploss/summary.csv"), daily("stoploss/daily_returns.csv")
    if not need(summ, r):
        return
    names = {"no_stop": "No stop", "stop_20": "Stop at -20%", "stop_25": "Stop at -25%"}
    colors = {n: SLOTS[i] for i, n in enumerate(names.values())}
    show(growth_chart(equity(r).rename(columns=names), colors, height=380))
    st.markdown("**Did stopped-out trades save money?** Each stopped trade is compared with the same trade "
                "in the no-stop run.")
    s = summ.set_index("variant").drop(index="no_stop", errors="ignore")
    fig = go.Figure()
    for col, name, colr in (("stops_saved_money", "Stop saved money", GAIN), ("stops_cost_money", "Stop cost money", LOSS)):
        fig.add_trace(go.Bar(x=[names.get(v, v) for v in s.index], y=s[col], name=name, marker_color=colr,
                             hovertemplate="%{x}: %{y} trades<extra>" + name + "</extra>"))
    show(style(fig, 300, "Stopped trades", hover="closest").update_layout(barmode="group", bargap=0.4, bargroupgap=0.1))
    st.dataframe(summ.set_index("variant").T.astype(str).replace("nan", ""), width="stretch")


def exp_variants():
    """Lookback / review-frequency variants: growth curves and CAGR vs drawdown scatter."""
    summ, r = load("variants/summary.csv"), daily("variants/daily_returns.csv")
    if not need(summ, r):
        return
    st.caption("3M/6M/12M lookback × review at month-end or every 30/45 days, all on the same common period, "
               "12 bps per side. The last column shows how CAGR moves when the review days shift.")
    names = list(summ["variant"])
    colors = {n: SLOTS[i % len(SLOTS)] for i, n in enumerate(names)}
    colors["equal_weight_bench"] = MUTED
    pick = st.multiselect("Variants", names, default=names)
    cols = [c for c in r.columns if c in pick or c == "equal_weight_bench"]
    show(growth_chart(equity(r[cols]), colors, {"equal_weight_bench": "dash"}, height=460)
         .update_layout(margin_t=80))

    st.markdown("**Return vs worst drawdown** (up and to the right is better)")
    s = summ[summ["variant"].isin(pick)]
    fig = go.Figure(go.Scatter(
        x=s["MaxDD_%"], y=s["CAGR_%"], mode="markers+text", text=s["variant"], textposition="top center",
        textfont=dict(color=INK2), marker=dict(size=12, color=[colors[v] for v in s["variant"]],
                                               line=dict(color=SURFACE, width=2)),
        customdata=s[["Sharpe", "trades"]],
        hovertemplate="%{text}<br>CAGR %{y:.1f}%, MaxDD %{x:.1f}%<br>Sharpe %{customdata[0]}, "
                      "%{customdata[1]} trades<extra></extra>"))
    show(style(fig, 360, "CAGR %", hover="closest").update_xaxes(title_text="Max drawdown %", showgrid=True,
                                                                gridcolor=GRID))
    st.dataframe(summ, width="stretch", hide_index=True)


def page_experiments():
    """Tabs for each experiment saved by run_all.sh."""
    st.title("Experiments")
    tabs = st.tabs(["Costs", "Volatility filter", "Stop-loss", "Lookback & review frequency"])
    for tab, fn in zip(tabs, (exp_costs, exp_volfilter, exp_stoploss, exp_variants)):
        with tab:
            fn()


@st.cache_resource(show_spinner="Loading prices from smallcap.duckdb ...")
def panel():
    """Price and traded-value tables from DuckDB, loaded once per session."""
    return bt.load_panel(str(DB))


@st.cache_data(show_spinner="Running backtest ...")
def run_cached(cfg_items: tuple):
    """Run backtest.run for a Cfg (passed as a hashable tuple) and return daily returns + report."""
    cfg = bt.Cfg(**dict(cfg_items))
    px, to = panel()
    out, _ = bt.run(px, to, cfg)
    return out, bt.report(out, cfg)


def page_run():
    """Rerun the backtest with custom rules and compare it with the default rules at the same cost."""
    st.title("Run a backtest")
    if not DB.exists():
        st.warning("smallcap.duckdb not found. Run `./run_all.sh` first.")
        return
    st.caption("Changes the rules and reruns the full backtest on smallcap.duckdb (a few seconds). "
               "Compared with the default rules at the same cost.")
    d = bt.Cfg()
    with st.form("cfg"):
        c1, c2, c3 = st.columns(3)
        lookback = c1.select_slider("Lookback (trading days)", [21, 42, 63, 126, 189, 252], d.lookback,
                                    help="63 ≈ 3 months, 126 ≈ 6 months, 252 ≈ 12 months")
        top_n = c1.slider("Stocks held (top N)", 5, 50, d.top_n)
        buffer = c1.slider("Sell when rank falls below", 5, 100, d.buffer, help="must be ≥ top N")
        cost = c2.slider("Cost per side (bps)", 0, 60, int(d.cost_bps), help="12 ≈ Zerodha charges, 40 = default")
        adtv = c2.slider("Min avg daily traded value (Rs crore)", 0.0, 10.0, d.min_adtv_cr, 0.5)
        start = c2.date_input("Start date", pd.Timestamp(d.start), min_value=pd.Timestamp("2016-01-01"))
        drop = c3.slider("Drop most volatile (%)", 0, 50, 0, 5, help="0 = volatility filter off")
        vwin = c3.select_slider("Volatility window (days)", [21, 42, 63, 126, 252], d.vol_window)
        vfreq = c3.radio("Volatility from", ["daily", "weekly"], horizontal=True)
        go_ = st.form_submit_button("Run backtest", type="primary")
    if buffer < top_n:
        st.error("'Sell when rank falls below' must be at least the number of stocks held.")
        return
    if not go_ and "ran" not in st.session_state:
        st.info("Pick settings and press **Run backtest**.")
        return
    st.session_state["ran"] = True

    cfg = dict(lookback=lookback, top_n=top_n, buffer=buffer, cost_bps=float(cost), min_adtv_cr=float(adtv),
               start=str(start), max_vol_pctile=1 - drop / 100, vol_window=vwin, vol_freq=vfreq)
    out, rep = run_cached(tuple(sorted(cfg.items())))
    base_out, base_rep = run_cached(tuple(sorted({"cost_bps": float(cost), "start": str(start)}.items())))

    st.subheader("Your settings")
    stat_tiles(rep["strategy_net"], base_rep["strategy_net"], rep["rs_1cr_becomes_cr"]["strategy_net"],
               base_rep["rs_1cr_becomes_cr"]["strategy_net"], rep["avg_annual_turnover_x"], "default rules")
    st.caption(f"Deltas compare with the default rules at {cost} bps. Period {rep['period']['start']} to "
               f"{rep['period']['end']}.")
    r = pd.DataFrame({"Your settings": out["net"], "Default rules": base_out["net"],
                      "Buy & hold": out["buy_hold"], "Equal-weight benchmark": out["bench"]})
    colors = {"Your settings": SLOTS[0], "Default rules": SLOTS[2], "Buy & hold": SLOTS[1],
              "Equal-weight benchmark": MUTED}
    eq = equity(r)
    show(growth_chart(eq, colors, {"Equal-weight benchmark": "dash"}))
    show(drawdown_chart(drawdown(eq[["Your settings", "Default rules"]]), colors))
    rows = {"Your settings": rep["strategy_net"], "Default rules": base_rep["strategy_net"],
            "Buy & hold": rep["buy_and_hold"], "Equal-weight benchmark": rep["benchmark_equal_weight"]}
    tbl = pd.DataFrame(rows).T
    tbl[["CAGR", "Vol", "MaxDD"]] *= 100
    st.dataframe(tbl.round(2).rename(columns={"CAGR": "CAGR %", "Vol": "Vol %", "MaxDD": "MaxDD %"}),
                 width="stretch")
    with st.expander("Settings used"):
        st.json(rep["config"])


nav = st.navigation([
    st.Page(page_overview, title="Overview", icon="📊", default=True),
    st.Page(page_trades, title="Trades", icon="🧾"),
    st.Page(page_experiments, title="Experiments", icon="🧪"),
    st.Page(page_run, title="Run a backtest", icon="⚙️"),
])
nav.run()
