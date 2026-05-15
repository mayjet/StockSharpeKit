"""
charts_mpl.py — Matplotlib chart builders.
Each function returns PNG bytes (io.BytesIO content) for st.download_button.
"""

from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import japanize_matplotlib  # noqa: F401 — enables Japanese fonts

import numpy as np
import pandas as pd
from pypfopt import EfficientFrontier

from analysis import AnalysisResult

FIG_W, FIG_H  = 12, 6
DPI           = 120
GRID_ALPHA    = 0.35
BAR_ALPHA     = 0.85
_PF_COLOR     = "#2563EB"
_BENCH_COLOR  = "#9CA3AF"
_SHORT_COLOR  = "#F59E0B"
_MDD_COLOR    = "#EF4444"
_OPT_COLOR    = "#EAB308"

# Per-benchmark defaults (cycling)
_BENCH_COLORS_M = ["#E67E22", "#16A085", "#8E44AD", "#E74C3C", "#2C3E50"]
_DEFAULT_BENCH_STYLES = ["dashed", "dotted", "dashdot", "solid", "dashed"]

STYLE_TO_LS = {
    "solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-.",
}

def _resolve(n_bench: int, custom: dict | None = None):
    """Return (pf_color, bench_colors, pf_ls, bench_ls)."""
    c = custom or {}
    pf_c = c.get("portfolio", _PF_COLOR)
    bl   = c.get("benchmarks", _BENCH_COLORS_M)
    pf_s = STYLE_TO_LS.get(c.get("portfolio_style", "solid"), "-")
    bs   = c.get("bench_styles", _DEFAULT_BENCH_STYLES)
    return (
        pf_c,
        [bl[i % len(bl)] for i in range(n_bench)],
        pf_s,
        [STYLE_TO_LS.get(bs[i % len(bs)], "--") for i in range(n_bench)],
    )


def _to_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=DPI)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── 1. Cumulative return bar ──────────────────────────────────────────────────

def mpl_cum_bar(result: AnalysisResult, L: dict, custom: dict | None = None) -> bytes:
    df = result.comparison_df[[L["col_portfolio"], L["col_cum_return"]]].copy()
    df[L["col_cum_return"]] = (
        df[L["col_cum_return"]].astype(str)
        .str.replace("%", "", regex=False).astype(float)
    )
    df = df.sort_values(L["col_cum_return"], ascending=False)

    labels = df[L["col_portfolio"]].tolist()
    values = df[L["col_cum_return"]].tolist()
    pf_c, bench_c, _, _ = _resolve(len(result.bench_tickers), custom)
    bench_names = [result.benchmark_labels[s] for s in result.bench_tickers]
    _cmap = {result.portfolio_name: pf_c}
    for i, bn in enumerate(bench_names):
        _cmap[bn] = bench_c[i]
    colors = [_cmap.get(lb, _BENCH_COLOR) for lb in labels]

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    bars = ax.bar(range(len(labels)), values, color=colors, alpha=BAR_ALPHA)
    ax.set_title(L["cum_bar_title"], fontsize=14)
    ax.set_ylabel(L["cum_bar_ylabel"], fontsize=11)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=10)
    ax.grid(axis="y", linestyle="--", alpha=GRID_ALPHA)
    for rect, val in zip(bars, values):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height(),
                f"{val:.2f}%", ha="center", va="bottom", fontsize=9)
    plt.tight_layout()
    return _to_bytes(fig)


# ── 2. Efficient frontier ─────────────────────────────────────────────────────

def mpl_efficient_frontier(result: AnalysisResult, L: dict) -> bytes:
    mu   = result.mu
    S    = result.S
    rfr  = result.risk_free_rate
    sym_to_name = dict(zip(result.confirmed_df["symbol"],
                           result.confirmed_df.get("name", result.confirmed_df["symbol"])))

    fig, ax = plt.subplots(figsize=(10, 6))   # 縦横比 3:5

    # Frontier curve
    target_returns = np.linspace(float(mu.min()), float(mu.max()), 50)
    vols, rets = [], []
    for r in target_returns:
        try:
            ef_tmp = EfficientFrontier(mu, S)
            ef_tmp.efficient_return(r)
            rp, vp, _ = ef_tmp.portfolio_performance()
            vols.append(float(vp) * 100)
            rets.append(float(rp) * 100)
        except Exception:
            pass
    if vols:
        ax.plot(vols, rets, linestyle="--", color="gray", label=L["chart_frontier_curve"])

    # CML
    if vols:
        cml_x = np.linspace(0, max(vols) * 1.1, 50)
        cml_y = rfr * 100 + result.sharpe * cml_x
        ax.plot(cml_x, cml_y, label=L["chart_cml"], color=_PF_COLOR)

    # Long-term assets
    long_tickers = [t for t in result.fund_tickers if t not in result.short_term_tickers]
    if long_tickers:
        vv = [float(np.sqrt(S.loc[t, t])) * 100 for t in long_tickers]
        rr = [float(mu[t]) * 100 for t in long_tickers]
        names = [f"{t}/{sym_to_name.get(t,t)}" for t in long_tickers]
        ax.scatter(vv, rr, label=L["chart_asset"], zorder=5)
        for i, name in enumerate(names):
            ax.annotate(name, (vv[i], rr[i]), fontsize=7, alpha=0.75)

    # Short-term
    if result.short_term_tickers:
        vv = [float(np.sqrt(S.loc[t, t])) * 100 for t in result.short_term_tickers if t in S.index]
        rr = [float(mu[t]) * 100 for t in result.short_term_tickers if t in mu.index]
        if vv:
            ax.scatter(vv, rr, color=_SHORT_COLOR, s=200, marker="^",
                       label=L["chart_short_term"], zorder=6)

    # High MDD
    if result.knockout_tickers:
        vv = [float(np.sqrt(S.loc[t, t])) * 100 for t in result.knockout_tickers if t in S.index]
        rr = [float(mu[t]) * 100 for t in result.knockout_tickers if t in mu.index]
        if vv:
            ax.scatter(vv, rr, color=_MDD_COLOR, s=80,
                       label=L["chart_high_mdd"], zorder=7)

    # Optimal
    ax.scatter(result.volatility * 100, result.expected_return * 100,
               marker="*", s=400, color=_OPT_COLOR, zorder=8,
               label=L["chart_optimal"])

    ax.set_title(L["ef_title"], fontsize=14)
    ax.set_xlabel(L["ef_xlabel"], fontsize=11)
    ax.set_ylabel(L["ef_ylabel"], fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=GRID_ALPHA)
    plt.tight_layout()
    return _to_bytes(fig)


# ── 3. Cumulative return line ─────────────────────────────────────────────────

def mpl_cum_line(result: AnalysisResult, L: dict, custom: dict | None = None) -> bytes:
    pf_c, bench_c, pf_ls, bench_ls = _resolve(len(result.bench_tickers), custom)
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))

    pf_cum = (1 + result.portfolio_returns).cumprod() - 1
    zero   = pd.Series([0.0], index=[pf_cum.index[0] - pd.DateOffset(months=1)])
    pf_cum = pd.concat([zero, pf_cum])
    ax.plot(pf_cum.index, pf_cum * 100,
            label=result.portfolio_name, color=pf_c, linewidth=2.5, linestyle=pf_ls)

    # Benchmarks
    for i, sym in enumerate(result.bench_tickers):
        label   = result.benchmark_labels[sym]
        bseries = result.bench_returns[sym].dropna()
        bseries = bseries.loc[result.portfolio_returns.index[0]:]
        cum     = (1 + bseries).cumprod() - 1
        zero    = pd.Series([0.0], index=[cum.index[0] - pd.DateOffset(months=1)])
        cum     = pd.concat([zero, cum])
        ax.plot(cum.index, cum * 100,
                label=label, color=bench_c[i], linewidth=1.5, linestyle=bench_ls[i])

    ax.set_title(L["cum_line_title"], fontsize=14)
    ax.set_xlabel(L["chart_date"], fontsize=11)
    ax.set_ylabel(L["chart_cum_ret"], fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=GRID_ALPHA)
    plt.tight_layout()
    return _to_bytes(fig)


# ── 4. Rolling Sharpe ─────────────────────────────────────────────────────────

def mpl_rolling_sharpe(result: AnalysisResult, L: dict, window: int = 12, custom: dict | None = None) -> bytes:
    pf_c, bench_c, pf_ls, bench_ls = _resolve(len(result.bench_tickers), custom)
    fig, ax = plt.subplots(figsize=(FIG_W, 5))

    def _rs(series: pd.Series) -> pd.Series:
        return (series.rolling(window).mean() / series.rolling(window).std()) * np.sqrt(12)

    rs_pf = _rs(result.portfolio_returns)
    ax.plot(rs_pf.index, rs_pf, label=result.portfolio_name,
            color=pf_c, linewidth=2.5, linestyle=pf_ls)

    for i, sym in enumerate(result.bench_tickers):
        rs = _rs(result.bench_returns[sym].dropna())
        ax.plot(rs.index, rs, label=result.benchmark_labels[sym],
                color=bench_c[i],
                linewidth=1.5,
                linestyle=bench_ls[i])

    ax.axhline(0, color="black", linewidth=0.8, linestyle=":")
    ax.set_title(L["roll_title"].format(w=window), fontsize=14)
    ax.set_xlabel(L["chart_date"], fontsize=11)
    ax.set_ylabel(L["roll_ylabel"], fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=GRID_ALPHA)
    plt.tight_layout()
    return _to_bytes(fig)


# ── 5. Drawdown ───────────────────────────────────────────────────────────────

def mpl_drawdown(result: AnalysisResult, L: dict, custom: dict | None = None) -> bytes:
    pf_c, bench_c, pf_ls, bench_ls = _resolve(len(result.bench_tickers), custom)

    def _dd(series: pd.Series) -> pd.Series:
        cum  = (1 + series).cumprod()
        peak = cum.cummax()
        return (cum / peak - 1) * 100

    fig, ax = plt.subplots(figsize=(FIG_W, 5))

    dd_pf = _dd(result.portfolio_returns)
    ax.fill_between(dd_pf.index, dd_pf, 0,
                    alpha=0.35, color=pf_c, label=result.portfolio_name)
    ax.plot(dd_pf.index, dd_pf, color=pf_c, linewidth=1.5)

    for i, sym in enumerate(result.bench_tickers):
        bseries = result.bench_returns[sym].dropna()
        bseries = bseries.loc[result.portfolio_returns.index[0]:]
        dd = _dd(bseries)
        ax.plot(dd.index, dd, label=result.benchmark_labels[sym],
                color=bench_c[i],
                linewidth=1.5,
                linestyle=bench_ls[i])

    ax.set_title(L["dd_title"], fontsize=14)
    ax.set_xlabel(L["chart_date"], fontsize=11)
    ax.set_ylabel(L["dd_ylabel"], fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=GRID_ALPHA)
    plt.tight_layout()
    return _to_bytes(fig)
