"""
charts_altair.py — Altair interactive chart builders.
Each function takes an AnalysisResult + lang dict and returns an alt.Chart.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import altair as alt

from analysis import AnalysisResult
from pypfopt import EfficientFrontier


# ── Palette ────────────────────────────────────────────────────────────────────
_PORTFOLIO_COLOR = "#2563EB"   # blue
_BENCH_COLOR     = "#9CA3AF"   # gray
_SHORT_COLOR     = "#F59E0B"   # amber
_MDD_COLOR       = "#EF4444"   # red
_OPTIMAL_COLOR   = "#EAB308"   # yellow

# Per-benchmark colors and dash patterns (cycling)
_BENCH_COLORS = ["#E67E22", "#16A085", "#8E44AD", "#E74C3C", "#2C3E50"]
_BENCH_DASHES = [[6, 4], [2, 2], [8, 4, 2, 4], [12, 6], []]

# ── Time axis helper ───────────────────────────────────────────────────────────
# 1月のみ "YYYY.1"、それ以外は月番号のみ "2", "3", ... と表示し、毎月縦グリッドを描画
_MONTH_LABEL_EXPR = (
    "month(datum.value) === 0 "
    "? (year(datum.value) + '.' + (month(datum.value) + 1)) "
    ": '' + (month(datum.value) + 1)"
)


def _time_x(title: str) -> alt.X:
    """月次グリッド線付き・1月に西暦表示の時系列 X 軸を返す。"""
    return alt.X(
        "date:T",
        title=title,
        axis=alt.Axis(
            tickCount="month",
            grid=True,
            gridColor="lightgray",
            gridOpacity=0.4,
            labelExpr=_MONTH_LABEL_EXPR,
        ),
    )


# ── 1. Weights bar chart ──────────────────────────────────────────────────────

def chart_weights(result: AnalysisResult, L: dict) -> alt.Chart:
    df = result.weights_df.copy()
    # Drop the "Total" row for the chart
    total_label = L["col_total"]
    df = df[df[L["col_ticker_name"]] != total_label].copy()
    df = df.sort_values(L["col_weight"], ascending=False)

    chart = (
        alt.Chart(df)
        .mark_bar(color=_PORTFOLIO_COLOR)
        .encode(
            x=alt.X(f'{L["col_weight"]}:Q',
                    title=L["chart_weight_pct"],
                    axis=alt.Axis(format=".1f")),
            y=alt.Y(f'{L["col_ticker_name"]}:N',
                    title=None,
                    sort="-x"),
            tooltip=[
                alt.Tooltip(f'{L["col_ticker_name"]}:N'),
                alt.Tooltip(f'{L["col_weight"]}:Q', format=".2f",
                            title=L["chart_weight_pct"]),
            ],
        )
        .properties(height=max(200, len(df) * 32))
    )
    return chart


# ── 2. Cumulative return bar chart ────────────────────────────────────────────

def chart_cum_bar(result: AnalysisResult, L: dict) -> alt.Chart:
    df = result.comparison_df[[L["col_portfolio"], L["col_cum_return"]]].copy()
    df[L["col_cum_return"]] = (
        df[L["col_cum_return"]]
        .astype(str).str.replace("%", "", regex=False)
        .astype(float)
    )
    df = df.sort_values(L["col_cum_return"], ascending=False).reset_index(drop=True)
    bench_names = [result.benchmark_labels[s] for s in result.bench_tickers]
    _color_map = {result.portfolio_name: _PORTFOLIO_COLOR}
    for i, bn in enumerate(bench_names):
        _color_map[bn] = _BENCH_COLORS[i % len(_BENCH_COLORS)]
    df["_color"] = df[L["col_portfolio"]].map(
        lambda n: _color_map.get(n, _BENCH_COLOR)
    )
    df["_label"] = df[L["col_cum_return"]].map(lambda v: f"{v:.2f}%")

    _x = alt.X(f'{L["col_portfolio"]}:N',
                title=None,
                sort=alt.EncodingSortField(field=L["col_cum_return"], order="descending"),
                axis=alt.Axis(labelAngle=-30))
    _y = alt.Y(f'{L["col_cum_return"]}:Q', title=L["cum_bar_ylabel"])
    _color = alt.Color("_color:N", scale=None, legend=None)
    _tooltip = [
        alt.Tooltip(f'{L["col_portfolio"]}:N'),
        alt.Tooltip(f'{L["col_cum_return"]}:Q', format=".2f", title=L["chart_cum_ret"]),
    ]

    bars = (
        alt.Chart(df)
        .mark_bar()
        .encode(x=_x, y=_y, color=_color, tooltip=_tooltip)
    )

    labels = (
        alt.Chart(df)
        .mark_text(baseline="bottom", dy=-4, fontSize=11)
        .encode(
            x=_x,
            y=_y,
            text=alt.Text("_label:N"),
            color=_color,
        )
    )

    return (bars + labels).properties(height=350)


# ── 3. Efficient Frontier ─────────────────────────────────────────────────────

def chart_efficient_frontier(result: AnalysisResult, L: dict) -> alt.LayerChart:
    mu   = result.mu
    S    = result.S
    rfr  = result.risk_free_rate

    # Build frontier curve
    target_returns = np.linspace(float(mu.min()), float(mu.max()), 60)
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

    frontier_df = pd.DataFrame({"vol": vols, "ret": rets})

    # Build asset scatter data
    asset_rows = []
    sym_to_name = dict(zip(result.confirmed_df["symbol"],
                           result.confirmed_df.get("name", result.confirmed_df["symbol"])))
    for t in result.fund_tickers:
        try:
            v = float(np.sqrt(S.loc[t, t])) * 100
            r = float(mu[t]) * 100
        except Exception:
            continue
        if t in result.knockout_tickers:
            atype = L["chart_high_mdd"]
        elif t in result.short_term_tickers:
            atype = L["chart_short_term"]
        else:
            atype = L["chart_asset"]
        asset_rows.append({
            "vol": v, "ret": r,
            "name": f"{t} / {sym_to_name.get(t, t)}",
            "type": atype,
        })
    asset_df = pd.DataFrame(asset_rows)

    # Optimal point
    opt_df = pd.DataFrame([{
        "vol": result.volatility * 100,
        "ret": result.expected_return * 100,
        "name": f"★ {result.portfolio_name}",
    }])

    # CML
    if vols:
        cml_x = np.linspace(0, max(vols) * 1.1, 40)
        cml_y = rfr * 100 + result.sharpe * cml_x
        cml_df = pd.DataFrame({"vol": cml_x, "ret": cml_y})
    else:
        cml_df = pd.DataFrame({"vol": [], "ret": []})

    # Color + shape scales
    color_domain = [L["chart_asset"], L["chart_short_term"], L["chart_high_mdd"]]
    color_range  = [_PORTFOLIO_COLOR, _SHORT_COLOR, _MDD_COLOR]
    shape_domain = [L["chart_asset"], L["chart_short_term"], L["chart_high_mdd"]]
    shape_range  = ["circle", "triangle-up", "circle"]

    # Layers
    frontier_line = (
        alt.Chart(frontier_df)
        .mark_line(strokeDash=[6, 3], color="gray", strokeWidth=1.5)
        .encode(x="vol:Q", y="ret:Q")
    )

    cml_line = (
        alt.Chart(cml_df)
        .mark_line(color=_PORTFOLIO_COLOR, strokeWidth=1.5)
        .encode(x="vol:Q", y="ret:Q")
    )

    if not asset_df.empty:
        asset_scatter = (
            alt.Chart(asset_df)
            .mark_point(size=80, filled=True, opacity=0.85)
            .encode(
                x=alt.X("vol:Q", title=L["chart_risk"]),
                y=alt.Y("ret:Q", title=L["chart_return"]),
                color=alt.Color("type:N",
                                scale=alt.Scale(domain=color_domain, range=color_range),
                                legend=alt.Legend(title=None)),
                shape=alt.Shape("type:N",
                                scale=alt.Scale(domain=shape_domain, range=shape_range),
                                legend=None),
                tooltip=[
                    alt.Tooltip("name:N", title=L["chart_asset"]),
                    alt.Tooltip("vol:Q", format=".2f", title=L["chart_risk"]),
                    alt.Tooltip("ret:Q", format=".2f", title=L["chart_return"]),
                    alt.Tooltip("type:N"),
                ],
            )
        )
    else:
        asset_scatter = alt.Chart(pd.DataFrame()).mark_point()

    optimal_point = (
        alt.Chart(opt_df)
        .mark_text(fontSize=26, color=_OPTIMAL_COLOR, fontWeight="bold", dy=-2)
        .encode(
            x="vol:Q", y="ret:Q",
            text=alt.value("★"),
            tooltip=[alt.Tooltip("name:N"), alt.Tooltip("vol:Q", format=".2f"),
                     alt.Tooltip("ret:Q", format=".2f")],
        )
    )

    return (
        alt.layer(frontier_line, cml_line, asset_scatter, optimal_point)
        .properties(height=504)   # 縦横比 3:5（基準幅 840px）
        .configure_legend(orient="bottom", columns=3)
    )


# ── 4. Cumulative return line chart ───────────────────────────────────────────

def chart_cum_line(result: AnalysisResult, L: dict) -> alt.Chart:
    rows: list[dict] = []

    # Portfolio
    pf = result.portfolio_returns
    pf_cum = (1 + pf).cumprod() - 1
    # Prepend a zero at the start
    zero_date = pf_cum.index[0] - pd.DateOffset(months=1)
    pf_cum = pd.concat([pd.Series([0.0], index=[zero_date]), pf_cum])
    for date, val in pf_cum.items():
        rows.append({
            "date": pd.Timestamp(date),
            "value": float(val) * 100,
            "series": result.portfolio_name,
            "dash": False,
        })

    # Benchmarks
    for sym in result.bench_tickers:
        label = result.benchmark_labels[sym]
        bseries = result.bench_returns[sym].dropna()
        if bseries.empty:
            continue
        bseries = bseries.loc[result.portfolio_returns.index[0]:]
        cum = (1 + bseries).cumprod() - 1
        zero_date = cum.index[0] - pd.DateOffset(months=1)
        cum = pd.concat([pd.Series([0.0], index=[zero_date]), cum])
        for date, val in cum.items():
            rows.append({
                "date": pd.Timestamp(date),
                "value": float(val) * 100,
                "series": label,
                "dash": False,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return alt.Chart(pd.DataFrame()).mark_line()

    # Assign per-series styles
    n_bench     = len(result.bench_tickers)
    bench_names = [result.benchmark_labels[s] for s in result.bench_tickers]
    all_series  = [result.portfolio_name] + bench_names
    colors      = [_PORTFOLIO_COLOR] + [_BENCH_COLORS[i % len(_BENCH_COLORS)] for i in range(n_bench)]
    widths      = [2.5] + [1.5] * n_bench
    dashes      = [[]] + [_BENCH_DASHES[i % len(_BENCH_DASHES)] for i in range(n_bench)]

    chart = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x=_time_x(L["chart_date"]),
            y=alt.Y("value:Q", title=L["chart_cum_ret"]),
            color=alt.Color("series:N",
                            scale=alt.Scale(domain=all_series, range=colors),
                            legend=alt.Legend(title=None)),
            strokeWidth=alt.StrokeWidth(
                "series:N",
                scale=alt.Scale(domain=all_series, range=widths),
                legend=None,
            ),
            strokeDash=alt.StrokeDash(
                "series:N",
                scale=alt.Scale(domain=all_series, range=dashes),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("date:T", title=L["chart_date"], format="%Y-%m"),
                alt.Tooltip("series:N", title=L["chart_series"]),
                alt.Tooltip("value:Q", format=".2f", title=L["chart_cum_ret"]),
            ],
        )
        .properties(height=420)
        .configure_legend(orient="bottom", columns=3)
    )
    return chart


# ── 5. Rolling Sharpe ─────────────────────────────────────────────────────────

def chart_rolling_sharpe(result: AnalysisResult, L: dict, window: int = 12) -> alt.LayerChart:
    rows: list[dict] = []

    def _rolling_sharpe(series: pd.Series) -> pd.Series:
        return (series.rolling(window).mean() / series.rolling(window).std()) * np.sqrt(12)

    rs_pf = _rolling_sharpe(result.portfolio_returns).dropna()
    for date, val in rs_pf.items():
        rows.append({"date": pd.Timestamp(date), "value": float(val),
                     "series": result.portfolio_name, "is_portfolio": True})

    for sym in result.bench_tickers:
        label = result.benchmark_labels[sym]
        rs = _rolling_sharpe(result.bench_returns[sym].dropna()).dropna()
        for date, val in rs.items():
            rows.append({"date": pd.Timestamp(date), "value": float(val),
                         "series": label, "is_portfolio": False})

    df = pd.DataFrame(rows)
    if df.empty:
        return alt.layer()

    n_bench    = len(result.bench_tickers)
    bench_names = [result.benchmark_labels[s] for s in result.bench_tickers]
    all_series = [result.portfolio_name] + bench_names
    colors     = [_PORTFOLIO_COLOR] + [_BENCH_COLORS[i % len(_BENCH_COLORS)] for i in range(n_bench)]
    widths     = [2.5] + [1.5] * n_bench
    dashes     = [[]] + [_BENCH_DASHES[i % len(_BENCH_DASHES)] for i in range(n_bench)]

    lines = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x=_time_x(L["chart_date"]),
            y=alt.Y("value:Q", title=L["chart_sharpe"]),
            color=alt.Color("series:N",
                            scale=alt.Scale(domain=all_series, range=colors),
                            legend=alt.Legend(title=None)),
            strokeWidth=alt.StrokeWidth(
                "series:N",
                scale=alt.Scale(domain=all_series, range=widths),
                legend=None,
            ),
            strokeDash=alt.StrokeDash(
                "series:N",
                scale=alt.Scale(domain=all_series, range=dashes),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("date:T", title=L["chart_date"], format="%Y-%m"),
                alt.Tooltip("series:N", title=L["chart_series"]),
                alt.Tooltip("value:Q", format=".3f", title=L["chart_sharpe"]),
            ],
        )
    )

    zero_df = pd.DataFrame({"y": [0]})
    zero_rule = (
        alt.Chart(zero_df)
        .mark_rule(strokeDash=[4, 3], color="black", strokeWidth=0.8)
        .encode(y="y:Q")
    )

    return (
        alt.layer(lines, zero_rule)
        .properties(height=350)   # 縦横比 5:12（基準幅 840px）
        .configure_legend(orient="bottom", columns=3)
    )


# ── 6. Drawdown ───────────────────────────────────────────────────────────────

def chart_drawdown(result: AnalysisResult, L: dict) -> alt.LayerChart:
    def _dd_series(series: pd.Series) -> pd.Series:
        cum  = (1 + series).cumprod()
        peak = cum.cummax()
        return (cum / peak - 1) * 100

    rows: list[dict] = []
    dd_pf = _dd_series(result.portfolio_returns)
    for date, val in dd_pf.items():
        rows.append({"date": pd.Timestamp(date), "value": float(val),
                     "series": result.portfolio_name, "is_portfolio": True})

    for sym in result.bench_tickers:
        label = result.benchmark_labels[sym]
        bseries = result.bench_returns[sym].dropna()
        bseries = bseries.loc[result.portfolio_returns.index[0]:]
        dd = _dd_series(bseries)
        for date, val in dd.items():
            rows.append({"date": pd.Timestamp(date), "value": float(val),
                         "series": label, "is_portfolio": False})

    df = pd.DataFrame(rows)
    if df.empty:
        return alt.layer()

    n_bench    = len(result.bench_tickers)
    all_series = [result.portfolio_name] + [result.benchmark_labels[s] for s in result.bench_tickers]
    colors     = [_PORTFOLIO_COLOR] + [_BENCH_COLORS[i % len(_BENCH_COLORS)] for i in range(n_bench)]
    widths     = [2.5] + [1.5] * n_bench

    pf_df    = df[df["is_portfolio"]]
    bench_df = df[~df["is_portfolio"]]

    area = (
        alt.Chart(pf_df)
        .mark_area(opacity=0.35, color=_PORTFOLIO_COLOR)
        .encode(
            x=_time_x(L["chart_date"]),
            y=alt.Y("value:Q", title=L["chart_drawdown_pct"]),
            tooltip=[
                alt.Tooltip("date:T", title=L["chart_date"], format="%Y-%m"),
                alt.Tooltip("value:Q", format=".2f", title=L["chart_drawdown_pct"]),
            ],
        )
    )
    pf_line = (
        alt.Chart(pf_df)
        .mark_line(color=_PORTFOLIO_COLOR, strokeWidth=2.5)
        .encode(
            x="date:T",
            y="value:Q",
            tooltip=[
                alt.Tooltip("date:T", title=L["chart_date"], format="%Y-%m"),
                alt.Tooltip("series:N", title=L["chart_series"]),
                alt.Tooltip("value:Q", format=".2f", title=L["chart_drawdown_pct"]),
            ],
        )
    )

    if not bench_df.empty:
        n_bench = len(result.bench_tickers)
        bench_names  = [result.benchmark_labels[s] for s in result.bench_tickers
                        if result.benchmark_labels[s] in bench_df["series"].values]
        bench_colors = [_BENCH_COLORS[i % len(_BENCH_COLORS)] for i in range(len(bench_names))]
        bench_widths = [1.5] * len(bench_names)
        bench_dashes = [_BENCH_DASHES[i % len(_BENCH_DASHES)] for i in range(len(bench_names))]
        bench_lines = (
            alt.Chart(bench_df)
            .mark_line()
            .encode(
                x="date:T",
                y="value:Q",
                color=alt.Color("series:N",
                                scale=alt.Scale(domain=bench_names,
                                                range=bench_colors),
                                legend=alt.Legend(title=None)),
                strokeWidth=alt.StrokeWidth(
                    "series:N",
                    scale=alt.Scale(domain=bench_names, range=bench_widths),
                    legend=None,
                ),
                strokeDash=alt.StrokeDash(
                    "series:N",
                    scale=alt.Scale(domain=bench_names, range=bench_dashes),
                    legend=None,
                ),
                tooltip=[
                    alt.Tooltip("date:T", title=L["chart_date"], format="%Y-%m"),
                    alt.Tooltip("series:N", title=L["chart_series"]),
                    alt.Tooltip("value:Q", format=".2f", title=L["chart_drawdown_pct"]),
                ],
            )
        )
        return (
            alt.layer(area, pf_line, bench_lines)
            .properties(height=350)
            .configure_legend(orient="bottom", columns=3)
        )

    return (
        alt.layer(area, pf_line)
        .properties(height=350)   # 縦横比 5:12（基準幅 840px）
    )
