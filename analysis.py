"""
analysis.py — Core portfolio analysis pipeline.
Ported from ex13.ipynb cells 19–25.

run_analysis() is the single entry point.
Returns an AnalysisResult dataclass with everything needed for charts/downloads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import json5
import numpy as np
import pandas as pd
import yfinance as yf
from pypfopt import EfficientFrontier, expected_returns, risk_models
from symbol_resolver import _yahoo_jp_fetch_monthly, _infer_country_from_symbol


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    # Settings snapshot
    portfolio_name:  str
    start_date:      str
    end_date:        str
    risk_free_rate:  float
    min_weight:      float
    user_country:    str
    mdd_threshold:   float
    min_req_months:  int
    timestamp:       str

    # Data
    confirmed_df:      pd.DataFrame           # symbol / name / exchange / country
    prices:            pd.DataFrame
    fund_tickers:      list[str]
    bench_tickers:     list[str]
    benchmark_labels:  dict[str, str]

    # Optimization outputs
    weights:          dict[str, float]        # {symbol: weight}
    weights_df:       pd.DataFrame            # display table
    expected_return:  float
    volatility:       float
    sharpe:           float

    # Classification
    short_term_tickers: list[str]
    knockout_tickers:   list[str]

    # Returns & metrics
    portfolio_returns: pd.Series
    bench_returns:     pd.DataFrame
    comparison_df:     pd.DataFrame           # full perf table

    # For efficient frontier chart
    mu: pd.Series
    S:  pd.DataFrame


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_benchmarks(json5_path: str, user_country: str):
    with open(json5_path, "r", encoding="utf-8") as f:
        data = json5.load(f)
    cfg        = data.get(user_country) or data["DEFAULT"]
    benchmarks = sorted(cfg["benchmarks"], key=lambda x: x.get("priority", 99))
    return cfg, benchmarks, data


def _max_drawdown(series: pd.Series) -> float:
    cummax = series.cummax()
    return float((series / cummax - 1.0).min())


def _perf_stats(series: pd.Series) -> tuple[float, float, float]:
    ann_ret = float(series.mean() * 12)
    ann_vol = float(series.std() * np.sqrt(12))
    cum_ret = float((1 + series).prod() - 1)
    return ann_ret, ann_vol, cum_ret


def _sharpe(ann_ret: float, ann_vol: float, rfr: float) -> float:
    if ann_vol == 0:
        return float("nan")
    return round((ann_ret - rfr) / ann_vol, 3)


def _calc_portfolio_returns(
    returns_df: pd.DataFrame, weights: pd.Series
) -> pd.Series:
    result: dict = {}
    for date, row in returns_df.iterrows():
        listed = row.dropna()
        if listed.empty:
            continue
        w     = weights[listed.index]
        w_sum = float(w.sum())
        if w_sum == 0:
            continue
        result[date] = float((listed * (w / w_sum)).sum())
    return pd.Series(result)


def _calc_risk_metrics(series: pd.Series, bench: pd.Series, L: dict) -> dict:
    aligned = pd.concat([series, bench], axis=1).dropna()
    cov     = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
    beta    = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else float("nan")
    var_95  = float(np.percentile(series.dropna(), 5))
    cvar_95 = float(series[series <= var_95].mean())
    excess  = series - bench.reindex(series.index)
    ir = (excess.mean() / excess.std() * np.sqrt(12)) if excess.std() > 0 else float("nan")
    return {
        L["col_beta"]:  round(beta, 3),
        L["col_var"]:   round(var_95, 4),
        L["col_cvar"]:  round(cvar_95, 4),
        L["col_ir"]:    round(ir, 3),
    }


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_analysis(
    confirmed_df: pd.DataFrame,
    portfolio_name:  str,
    start_date:      str,
    end_date:        str,
    risk_free_rate:  float,
    min_weight:      float,
    user_country:    str,
    mdd_threshold:   float,
    min_req_months:  int,
    benchmarks_path: str,
    lang_dict:       dict,                    # _L[lang] for column names
    progress_cb:     Callable[[str], None] | None = None,
    comparison_fund_symbols: list[str] | None = None,
    comparison_fund_name:    str | None = None,
) -> AnalysisResult:
    """
    Full analysis pipeline. Returns AnalysisResult.
    progress_cb(message) is called at each step for UI feedback.
    """
    L = lang_dict

    def _progress(msg: str):
        if progress_cb:
            progress_cb(msg)

    # ── Step 1: Load benchmarks ───────────────────────────────────────────
    country_cfg, benchmark_defs, benchmark_master = _load_benchmarks(
        benchmarks_path, user_country
    )
    benchmark_tickers = [b["symbol"] for b in benchmark_defs]
    benchmark_labels  = {b["symbol"]: b["name"] for b in benchmark_defs}

    # ── Step 2: Download prices ───────────────────────────────────────────
    _progress(L.get("step_download", "Downloading prices..."))
    fund_tickers = confirmed_df["symbol"].dropna().unique().tolist()
    # Comparison funds: deduplicate against portfolio and index benchmarks
    comp_symbols = [s for s in (comparison_fund_symbols or [])
                    if s not in fund_tickers and s not in benchmark_tickers]
    all_tickers  = sorted(set(fund_tickers + benchmark_tickers + comp_symbols))

    prices_raw = yf.download(
        all_tickers,
        start    = start_date,
        end      = end_date,
        interval = "1mo",
        progress = False,
        auto_adjust = True,
    )

    if isinstance(prices_raw.columns, pd.MultiIndex):
        prices = prices_raw["Close"].copy()
    else:
        prices = prices_raw.copy()

    prices = prices.dropna(axis=1, how="all")

    # Yahoo Finance 国際 API にない JP 株への価格フォールバック
    for _tlist, _label in [(fund_tickers, ""), (comp_symbols, " (comparison)")]:
        _missing = [t for t in _tlist if t not in prices.columns or prices[t].isna().all()]
        for t in _missing:
            if _infer_country_from_symbol(t) == "JP":
                _progress(L.get("step_download", "Downloading prices...") + f" ({t} → Yahoo Finance Japan…){_label}")
                jp_s = _yahoo_jp_fetch_monthly(t, start_date, end_date)
                if not jp_s.empty:
                    prices[t] = jp_s.reindex(prices.index, method="ffill")

    fund_tickers  = [t for t in fund_tickers  if t in prices.columns]
    bench_tickers = [t for t in benchmark_tickers if t in prices.columns]
    comp_tickers  = [t for t in comp_symbols if t in prices.columns]
    prices = prices[fund_tickers + bench_tickers + comp_tickers]

    # FX conversion
    _base_currency  = country_cfg.get("base_currency", "USD")
    _fx_tickers_map = country_cfg.get("fx_tickers", {})
    _country_to_currency = {
        cc: benchmark_master[cc]["base_currency"]
        for cc in benchmark_master
        if cc not in ("DEFAULT",) and "base_currency" in benchmark_master.get(cc, {})
    }

    _fx_cache: dict[str, pd.Series] = {}
    for t in fund_tickers:
        row = confirmed_df.loc[confirmed_df["symbol"] == t, "country"]
        if row.empty:
            continue
        src_ccy  = _country_to_currency.get(row.values[0])
        if src_ccy and src_ccy != _base_currency:
            fx_entry = _fx_tickers_map.get(src_ccy)
            if not fx_entry:
                continue
            if isinstance(fx_entry, dict):
                fx_ticker = fx_entry["ticker"]
                fx_invert = fx_entry.get("invert", False)
            else:
                fx_ticker = fx_entry
                fx_invert = False
            if fx_ticker not in _fx_cache:
                fx_raw = yf.download(
                    fx_ticker, start=start_date, end=end_date,
                    interval="1mo", progress=False, auto_adjust=True,
                )
                if isinstance(fx_raw.columns, pd.MultiIndex):
                    fx_s = fx_raw["Close"].squeeze()
                else:
                    fx_s = fx_raw.squeeze()
                _fx_cache[fx_ticker] = fx_s.reindex(prices.index, method="ffill")
            fx_rate = _fx_cache[fx_ticker]
            prices[t] = prices[t] / fx_rate if fx_invert else prices[t] * fx_rate

    # ── Step 3: Short-term check ──────────────────────────────────────────
    _progress(L.get("step_shortterm", "Checking short-term assets..."))
    month_counts = prices[fund_tickers].notna().sum()
    short_term_tickers = [t for t in fund_tickers if month_counts[t] < min_req_months]
    long_term_tickers  = [t for t in fund_tickers if t not in short_term_tickers]

    # ── Step 4: Max drawdown ──────────────────────────────────────────────
    _progress(L.get("step_mdd", "Computing max drawdown..."))
    mdd_dict: dict[str, float] = {}
    for t in fund_tickers:
        s = prices[t].dropna()
        if len(s) >= 2:
            mdd_dict[t] = _max_drawdown(s)
    knockout_tickers = [t for t, v in mdd_dict.items() if v <= mdd_threshold]

    # ── Step 5: Returns ───────────────────────────────────────────────────
    returns      = prices.pct_change()
    fund_returns  = returns[fund_tickers].dropna(how="all")
    bench_returns = returns[bench_tickers].dropna(how="all")

    # ── Step 5b: Comparison fund (same optimization as main) ────────────
    _COMP_KEY = "__comp_fund__"
    if comp_tickers:
        _progress(L.get("step_optimize", "Optimizing portfolio...") + " (comparison)")
        comp_returns_all = returns[comp_tickers].dropna(how="all")
        comp_mu = expected_returns.mean_historical_return(
            prices[comp_tickers], frequency=12, compounding=False
        )
        _comp_ret_cov = comp_returns_all.dropna()
        if len(_comp_ret_cov) < max(12, len(comp_tickers) + 1):
            _comp_ret_cov = comp_returns_all.fillna(0)
        comp_S = risk_models.CovarianceShrinkage(
            _comp_ret_cov, returns_data=True, frequency=12
        ).ledoit_wolf()

        comp_n = len(comp_tickers)
        comp_eff_min_w = min(min_weight, 1.0 / comp_n) if comp_n > 0 else min_weight
        comp_opt_rfr = risk_free_rate if float(comp_mu.max()) > risk_free_rate else 0.0

        def _build_comp_ef() -> EfficientFrontier:
            ef_ = EfficientFrontier(comp_mu, comp_S)
            if comp_eff_min_w > 0:
                ef_.add_constraint(lambda w: w >= comp_eff_min_w)
            return ef_

        comp_ef = _build_comp_ef()
        try:
            comp_ef.max_sharpe(risk_free_rate=comp_opt_rfr)
        except Exception:
            comp_ef = _build_comp_ef()
            comp_ef.min_volatility()

        comp_weights = pd.Series(comp_ef.clean_weights())
        comp_portfolio = _calc_portfolio_returns(comp_returns_all, comp_weights)
        if not comp_portfolio.empty:
            bench_returns[_COMP_KEY] = comp_portfolio
            bench_tickers.append(_COMP_KEY)
            benchmark_labels[_COMP_KEY] = comparison_fund_name or "Comparison Fund"

    # ── Step 6: Optimization ──────────────────────────────────────────────
    _progress(L.get("step_optimize", "Optimizing portfolio..."))
    mu = expected_returns.mean_historical_return(
        prices[fund_tickers], frequency=12, compounding=False
    )
    _returns_for_cov = fund_returns.dropna()
    if len(_returns_for_cov) < max(12, len(fund_tickers) + 1):
        _returns_for_cov = fund_returns.fillna(0)
    S = risk_models.CovarianceShrinkage(
        _returns_for_cov, returns_data=True, frequency=12
    ).ledoit_wolf()

    n_assets = len(fund_tickers)
    # Cap min_weight so that n_assets * min_weight <= 1 (otherwise infeasible)
    effective_min_weight = min(min_weight, 1.0 / n_assets) if n_assets > 0 else min_weight

    # If all expected returns <= risk_free_rate, max_sharpe is unbounded; use rfr=0
    opt_rfr = risk_free_rate if float(mu.max()) > risk_free_rate else 0.0

    def _build_ef() -> EfficientFrontier:
        ef_ = EfficientFrontier(mu, S)
        if effective_min_weight > 0:
            ef_.add_constraint(lambda w: w >= effective_min_weight)
        return ef_

    ef = _build_ef()
    try:
        ef.max_sharpe(risk_free_rate=opt_rfr)
    except Exception:
        # Fallback: min volatility portfolio
        ef = _build_ef()
        ef.min_volatility()

    weights        = ef.clean_weights()
    weights_series = pd.Series(weights)
    exp_ret, vol, sharpe = ef.portfolio_performance(risk_free_rate=risk_free_rate)

    # ── Step 7: Portfolio returns ─────────────────────────────────────────
    portfolio_returns = _calc_portfolio_returns(fund_returns, weights_series)

    # ── Step 8: Risk metrics + comparison table ───────────────────────────
    _progress(L.get("step_risk", "Computing risk metrics..."))
    _primary_bench = bench_tickers[0] if bench_tickers else None

    _pf_idx = portfolio_returns.index
    rows: list[list] = []
    pr = _perf_stats(portfolio_returns)
    rows.append([portfolio_name,
                 _sharpe(pr[0], pr[1], risk_free_rate),
                 pr[0], pr[1], pr[2]])
    for sym in bench_tickers:
        br = _perf_stats(bench_returns[sym].reindex(_pf_idx).dropna())
        rows.append([benchmark_labels[sym],
                     _sharpe(br[0], br[1], risk_free_rate),
                     br[0], br[1], br[2]])

    comparison_df = pd.DataFrame(
        rows,
        columns=[L["col_portfolio"], L["col_sharpe"],
                 L["col_ann_return"], L["col_ann_risk"], L["col_cum_return"]]
    )

    if _primary_bench:
        _bench_clipped = bench_returns[_primary_bench].reindex(_pf_idx).dropna()
        pm = _calc_risk_metrics(portfolio_returns, _bench_clipped, L)
        for col, val in pm.items():
            comparison_df.loc[comparison_df[L["col_portfolio"]] == portfolio_name, col] = val
        for sym in bench_tickers:
            bm = _calc_risk_metrics(
                bench_returns[sym].reindex(_pf_idx).dropna(), _bench_clipped, L
            )
            for col, val in bm.items():
                comparison_df.loc[comparison_df[L["col_portfolio"]] == benchmark_labels[sym], col] = val

    # ── Step 9: Weights display table ─────────────────────────────────────
    sym_to_name = dict(zip(confirmed_df["symbol"], confirmed_df.get("name", confirmed_df["symbol"])))
    weight_rows = [
        [f"{sym} / {sym_to_name.get(sym, sym)}", round(w * 100, 2)]
        for sym, w in weights.items() if w > 0
    ]
    weight_rows.append([L["col_total"], round(sum(w for w in weights.values() if w > 0) * 100, 2)])
    weights_df = pd.DataFrame(weight_rows, columns=[L["col_ticker_name"], L["col_weight"]])

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return AnalysisResult(
        portfolio_name     = portfolio_name,
        start_date         = start_date,
        end_date           = end_date,
        risk_free_rate     = risk_free_rate,
        min_weight         = min_weight,
        user_country       = user_country,
        mdd_threshold      = mdd_threshold,
        min_req_months     = min_req_months,
        timestamp          = timestamp,
        confirmed_df       = confirmed_df,
        prices             = prices,
        fund_tickers       = fund_tickers,
        bench_tickers      = bench_tickers,
        benchmark_labels   = benchmark_labels,
        weights            = dict(weights),
        weights_df         = weights_df,
        expected_return    = float(exp_ret),
        volatility         = float(vol),
        sharpe             = float(sharpe),
        short_term_tickers = short_term_tickers,
        knockout_tickers   = knockout_tickers,
        portfolio_returns  = portfolio_returns,
        bench_returns      = bench_returns,
        comparison_df      = comparison_df,
        mu                 = mu,
        S                  = S,
    )
