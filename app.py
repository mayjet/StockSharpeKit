"""
app.py — Max Sharpe Portfolio Analyzer
Run:  streamlit run app.py
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd
import streamlit as st

import streamlit.components.v1 as components

from lang import get_text, _L
from symbol_input_component import render_symbol_table, handle
from analysis import run_analysis
import charts_altair as ca
import charts_mpl    as cm
from downloads import (
    build_analysis_xlsx, build_resolved_xlsx,
    build_output_json, build_zip,
)

st.set_page_config(
    page_title="Max Sharpe Portfolio Analyzer",
    page_icon="📈",
    layout="wide",
)

BENCHMARKS_PATH = "benchmarks.json5"
COUNTRY_OPTIONS = ["JP","US","GB","DE","FR","CN","HK","IN"]

_EXTRA = {
    "JP": {
        "hint_dblclick":          "クリックで編集",
        "hint_cancel_edit":       "編集をキャンセル",
        "hint_click_to_edit":     "クリックで再編集",
        "status_confirmed_short": "確定",
        "status_searching":       "検索中…",
        "status_duplicate":       "重複",
        "msg_duplicate":          "重複のため除外されました",
    },
    "EN": {
        "hint_dblclick":          "Click to edit",
        "hint_cancel_edit":       "Cancel edit",
        "hint_click_to_edit":     "Click to re-edit",
        "status_confirmed_short": "OK",
        "status_searching":       "Searching…",
        "status_duplicate":       "Duplicate",
        "msg_duplicate":          "Duplicate — skipped",
    },
}

def _T(k): return get_text(k, st.session_state.get("lang","JP"))
def _labels(lang): return {**_L.get(lang,_L["JP"]), **_EXTRA.get(lang,_EXTRA["JP"])}


def _init():
    today = date.today()
    _sd_default = today - timedelta(days=3 * 365)
    for k, v in dict(
        lang="JP", portfolio_name="MyPortfolio",
        start_date=_sd_default, end_date=today,
        risk_free_rate=0.001, min_weight=0.0,
        user_country="JP", mdd_threshold=-50, min_req_months=36,
        ticker_rows=[], analysis_result=None, chart_bytes={},
        _sym_last_seq=-9999, _sym_search_results=None,
    ).items():
        if k not in st.session_state:
            st.session_state[k] = v
    # 旧セッションで start_date が None のまま残っている場合の救済
    if st.session_state.start_date is None:
        st.session_state.start_date = _sd_default
    if st.session_state.end_date is None or st.session_state.end_date > today:
        st.session_state.end_date = today


_DATE_JS = """
<script>
(function () {
  var parentDoc = window.parent.document;

  // ── 既存値の右シフトを防ぐための DOM クリア用 setter ──────────────────
  var nativeSetter = Object.getOwnPropertyDescriptor(
    window.parent.HTMLInputElement.prototype, 'value'
  ).set;

  // ── 個別入力欄へのパッチ ──────────────────────────────────────────────
  function patch(input) {
    if (input._datePatchDone) return;
    input._datePatchDone = true;
    input._clearPending  = false;

    // 数値キーボード要求
    input.setAttribute("inputmode",      "numeric");

    // iOS 自動変換・補正を全面無効化
    input.setAttribute("autocomplete",   "off");
    input.setAttribute("autocorrect",    "off");
    input.setAttribute("autocapitalize", "none");
    input.setAttribute("spellcheck",     "false");

    // 日本語キーボードの IME 変換イベントを React に届かせない
    ["compositionstart", "compositionend", "compositionupdate"].forEach(function(ev) {
      input.addEventListener(ev, function(e) { e.stopPropagation(); }, true);
    });

    // フォーカス時に「最初の1打でクリア」フラグを立てる
    input.addEventListener("focus", function () {
      input._clearPending = true;
    }, false);
    input.addEventListener("blur", function () {
      input._clearPending = false;
    }, false);
  }

  // ── 親ページへの keydown capture リスナー（React より先に動く） ────────
  // 重複登録防止
  if (!parentDoc._dateKeydownPatched) {
    parentDoc._dateKeydownPatched = true;

    parentDoc.addEventListener("keydown", function (e) {
      var input = e.target;
      if (!input || !input._datePatchDone) return;
      if (!input._clearPending)            return;
      if (!/^[0-9]$/.test(e.key))          return;

      // 最初の数字キーが React に届く前に DOM 値だけ空にする。
      // React はこのキーを「空フィールドへの入力」として処理するため
      // 既存の年桁との右シフト混入（例: 2022→2202）が起きなくなる。
      input._clearPending = false;
      nativeSetter.call(input, "");
      // ※ input/change イベントは発火しない → Streamlit state は変わらず
      //    React が後続の keydown を処理して年セクションを "2___" から開始する
    }, true); // capture = React のデリゲートより前
  }

  // ── MutationObserver で動的に追加された入力欄もパッチ ─────────────────
  function findAndPatch() {
    parentDoc.querySelectorAll('[data-testid="stDateInputField"] input').forEach(patch);
  }

  findAndPatch();
  new MutationObserver(findAndPatch).observe(
    parentDoc.body,
    { subtree: true, childList: true }
  );
})();
</script>
"""


def _inject_date_js():
    components.html(_DATE_JS, height=0)


def _top_bar():
    c1, c2 = st.columns([6, 1])
    c1.markdown("## Max Sharpe Portfolio Analyzer")
    with c2:
        _opts   = ["JP", "EN"]
        _labels = {"JP": "日本語", "EN": "English"}
        sel = st.selectbox(
            "",
            options=_opts,
            index=_opts.index(st.session_state.lang),
            format_func=lambda x: _labels[x],
            label_visibility="collapsed",
            key="lang_sel",
        )
        if sel != st.session_state.lang:
            st.session_state.lang = sel
            st.rerun()
    st.divider()



def _basic():
    st.markdown(_T("app_description"))
    st.write("")
    # ── ポートフォリオ名（全幅）──────────────────────────────────────────
    st.session_state.portfolio_name = st.text_input(
        _T("label_portfolio_name"), value=st.session_state.portfolio_name, key="pf"
    )
    # ── 分析期間（2カラム：date_input + iOS 自動変換防止 JS）────────────
    today = date.today()
    c1, c2 = st.columns(2)
    with c1:
        sd = st.date_input(
            _T("label_start_date"),
            value=st.session_state.start_date,
            max_value=today,
            key="sd_cal",
        )
        st.session_state.start_date = sd
    with c2:
        ed = st.date_input(
            _T("label_end_date"),
            value=min(st.session_state.end_date, today),
            max_value=today,
            key="ed_cal",
        )
        st.session_state.end_date = ed
    _inject_date_js()


def _advanced():
    with st.expander(_T("section_advanced"),expanded=False):
        c1,c2,c3=st.columns(3)
        with c1:
            st.session_state.risk_free_rate=st.number_input(
                _T("label_risk_free_rate"),value=float(st.session_state.risk_free_rate),
                step=0.0001,format="%.4f",key="rfr")
            st.caption(_T("desc_risk_free_rate"))
        with c2:
            st.session_state.min_weight=st.number_input(
                _T("label_min_weight"),value=float(st.session_state.min_weight),
                min_value=0.0,max_value=1.0,step=0.01,format="%.2f",key="mw")
            st.caption(_T("desc_min_weight"))
        with c3:
            idx=COUNTRY_OPTIONS.index(st.session_state.user_country) \
                if st.session_state.user_country in COUNTRY_OPTIONS else 0
            nc=st.selectbox(_T("label_user_country"),COUNTRY_OPTIONS,index=idx,key="ctry")
            if nc!=st.session_state.user_country:
                st.session_state.user_country=nc
            st.caption(_T("desc_user_country"))
        c4,c5=st.columns(2)
        with c4:
            st.session_state.mdd_threshold=st.slider(
                _T("label_mdd_threshold"),-100,0,step=5,
                value=int(st.session_state.mdd_threshold),format="%d%%",key="mdd")
            st.caption(_T("desc_mdd_threshold"))
        with c5:
            st.session_state.min_req_months=st.number_input(
                _T("label_min_months"),value=int(st.session_state.min_req_months),
                min_value=1,max_value=120,step=1,key="mon")
            st.caption(_T("desc_min_months"))


def _symbols():
    st.subheader(_T("section_symbols"))
    st.caption(_T("sym_table_hint"))

    lang    = st.session_state.lang
    country = st.session_state.user_country

    cv = render_symbol_table(
        rows           = st.session_state.ticker_rows,
        lang           = lang,
        country        = country,
        labels         = _labels(lang),
        search_results = st.session_state.get("_sym_search_results"),
        key            = "sym_table",
    )

    action = handle(cv)

    if action == "new_results":
        st.rerun()                   # push results to component

    if action == "rows_update":
        st.session_state._sym_search_results = None

    # Duplicate toast
    dupes = st.session_state.pop("_dup_notice", [])
    if dupes:
        st.toast(
            f"⚠️ {', '.join(dupes)} — {_T('msg_duplicate')}",
            icon="⚠️",
        )


def _run_button():
    rows = st.session_state.ticker_rows
    ok   = [r for r in rows if r.get("confirmed")]
    bad  = [r for r in rows if not r.get("confirmed")
            and not r.get("duplicate") and r.get("symbol","").strip()]
    bad_order = (
        st.session_state.start_date is not None
        and st.session_state.start_date >= st.session_state.end_date
    )
    st.write("")
    if not ok:      st.info(_T("warn_no_confirmed"))
    elif bad:       st.warning(_T("warn_has_unconfirmed"))
    if bad_order:   st.warning(_T("warn_date_order"))
    blocked = not ok or bool(bad) or bad_order
    return st.button(_T("btn_run"),type="primary", disabled=blocked, key="run")


def _autosave(res, L: dict, chart_bytes: dict) -> None:
    """分析結果を ./portfolios/<name>_<timestamp>/ に自動保存する（zip 以外）。"""
    ts      = res.timestamp.replace("-", ".").replace(" ", "_").replace(":", ".")
    out_dir = Path("portfolios") / f"{res.portfolio_name}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis_results.xlsx").write_bytes(build_analysis_xlsx(res, L))
    (out_dir / "resolved_symbols.xlsx").write_bytes(build_resolved_xlsx(res.confirmed_df))
    (out_dir / "output.json").write_bytes(build_output_json(res, L))
    for fname, data in chart_bytes.items():
        if data:
            (out_dir / fname).write_bytes(data)


def _analyse():
    L   = _L[st.session_state.lang]
    cdf = pd.DataFrame([
        dict(input=r["symbol"],symbol=r["symbol"],name=r.get("name",""),
             exchange=r.get("exchange",""),country=r.get("country",""))
        for r in st.session_state.ticker_rows if r.get("confirmed")
    ])
    msgs=[]; ph=st.empty()
    def _p(m): msgs.append(m); ph.info("  \n".join(msgs))
    try:
        res=run_analysis(
            confirmed_df    = cdf,
            portfolio_name  = st.session_state.portfolio_name,
            start_date      = str(st.session_state.start_date),
            end_date        = str(st.session_state.end_date),
            risk_free_rate  = float(st.session_state.risk_free_rate),
            min_weight      = float(st.session_state.min_weight),
            user_country    = st.session_state.user_country,
            mdd_threshold   = float(st.session_state.mdd_threshold)/100,
            min_req_months  = int(st.session_state.min_req_months),
            benchmarks_path = BENCHMARKS_PATH,
            lang_dict       = L,
            progress_cb     = _p,
        )
        _p(_T("step_done"))
        st.session_state.analysis_result=res
        chart_bytes={
            "cumulative_return_summary.png":    cm.mpl_cum_bar(res,L),
            "efficient_frontier.png":           cm.mpl_efficient_frontier(res,L),
            "cumulative_return_timeseries.png": cm.mpl_cum_line(res,L),
            "rolling_sharpe.png":               cm.mpl_rolling_sharpe(res,L),
            "drawdown.png":                     cm.mpl_drawdown(res,L),
        }
        st.session_state.chart_bytes=chart_bytes
        _autosave(res, L, chart_bytes)
    except Exception as e:
        ph.error(f"{_T('analysis_error')}: {e}"); raise
    finally:
        ph.empty()


def _sec(t,d): st.subheader(_T(t)); st.markdown(_T(d))
def _dl(f):
    d=st.session_state.chart_bytes.get(f,b"")
    if d: st.download_button(_T("btn_download_png"),d,f,"image/png",key=f"dl_{f}")

def _results():
    res=st.session_state.analysis_result
    if res is None: return
    L=_L[st.session_state.lang]
    st.divider()

    _sec("section_weights","desc_weights")
    c1,c2=st.columns([1.2,1])
    with c1: st.dataframe(res.weights_df,use_container_width=True,hide_index=True)
    with c2:
        try: st.altair_chart(ca.chart_weights(res,L),use_container_width=True)
        except Exception as e: st.warning(str(e))

    st.divider(); _sec("section_performance","desc_performance")
    _pct = st.column_config.NumberColumn(format=".2%")
    _num = st.column_config.NumberColumn(format=".3f")
    st.dataframe(
        res.comparison_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            L["col_sharpe"]:     _num,
            L["col_ann_return"]: _pct,
            L["col_ann_risk"]:   _pct,
            L["col_cum_return"]: _pct,
            L["col_var"]:        _pct,
            L["col_cvar"]:       _pct,
            L["col_beta"]:       _num,
            L["col_ir"]:         _num,
        },
    )
    xlsx_b=build_analysis_xlsx(res,L); res_b=build_resolved_xlsx(res.confirmed_df)
    st.download_button(_T("download_xlsx"),xlsx_b,"analysis_results.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key="xl")

    st.divider(); _sec("section_cum_bar","desc_cum_bar")
    try: st.altair_chart(ca.chart_cum_bar(res,L),use_container_width=True)
    except Exception as e: st.warning(str(e))
    _dl("cumulative_return_summary.png")

    st.divider(); _sec("section_frontier","desc_frontier")
    try: st.altair_chart(ca.chart_efficient_frontier(res,L),use_container_width=True)
    except Exception as e: st.warning(str(e))
    _dl("efficient_frontier.png")

    st.divider(); _sec("section_cum_line","desc_cum_line")
    try: st.altair_chart(ca.chart_cum_line(res,L),use_container_width=True)
    except Exception as e: st.warning(str(e))
    _dl("cumulative_return_timeseries.png")

    st.divider(); _sec("section_rolling","desc_rolling")
    try: st.altair_chart(ca.chart_rolling_sharpe(res,L),use_container_width=True)
    except Exception as e: st.warning(str(e))
    _dl("rolling_sharpe.png")

    st.divider(); _sec("section_drawdown","desc_drawdown")
    try: st.altair_chart(ca.chart_drawdown(res,L),use_container_width=True)
    except Exception as e: st.warning(str(e))
    _dl("drawdown.png")

    st.divider(); st.subheader(_T("btn_download_all"))
    json_b=build_output_json(res,L)
    zip_b=build_zip(xlsx_bytes=xlsx_b,resolved_bytes=res_b,
                    json_bytes=json_b,chart_bytes=st.session_state.chart_bytes)
    _ts = res.timestamp.replace("-", ".").replace(" ", "_").replace(":", ".")
    _zip_name = f"{res.portfolio_name}_{_ts}.zip"
    cz,cj,cr=st.columns(3)
    cz.download_button(_T("btn_download_all"),zip_b,
        _zip_name,"application/zip",key="zip")
    cj.download_button(_T("download_json"),json_b,"output.json",
        "application/json",key="json_dl")
    cr.download_button(_T("download_resolved"),res_b,"resolved_symbols.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key="res_dl")


def main():
    _init(); _top_bar(); _basic(); _advanced()
    st.write(""); _symbols()
    st.write("")
    if _run_button():
        with st.spinner(""): _analyse()
        st.rerun()
    _results()

if __name__=="__main__":
    main()