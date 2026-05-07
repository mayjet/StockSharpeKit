"""
symbol_input.py — Pure-Streamlit symbol input table.

Key changes vs previous version
  • st.text_area replaces st.text_input  →  multi-line paste is captured
    (st.text_input strips newlines at the HTML level; text_area preserves them)
  • on_change detects bulk content → runs best_match per token → creates rows
  • Duplicate symbols are rejected with st.toast notification
  • Confirmed-row cells use normal-size text (not st.caption)
  • Add-button margin is flush with the table
"""

from __future__ import annotations
import re
import streamlit as st
from symbol_resolver import search_suggestions, best_match

# ── Column proportions [symbol | name | exchange | country | status | del] ────
_COLS = [1.5, 2.6, 1.2, 0.8, 1.1, 0.45]

# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """
<style>
/* ── Header labels ──────────────────────────────────────── */
.sym-th {
    font-size: 11px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: .07em !important;
    opacity: .52 !important;
    margin: 0 !important;
    padding: 5px 0 3px !important;
    line-height: 1 !important;
}

/* ── Row separators ─────────────────────────────────────── */
.sym-sep {
    border: none;
    border-top: 1px solid rgba(49,51,63,.08);
    margin: 0 !important;
}
[data-theme="dark"] .sym-sep { border-top-color: rgba(250,250,250,.08); }

.sym-sep-heavy {
    border: none;
    border-top: 2px solid rgba(49,51,63,.17);
    margin: 2px 0 0 !important;
}
[data-theme="dark"] .sym-sep-heavy { border-top-color: rgba(250,250,250,.17); }

/* ── text_area styled to look like single-line input ────── */
.sym-input-wrap textarea {
    min-height: 42px !important;
    max-height: 42px !important;
    height:     42px !important;
    resize: none !important;
    overflow-y: hidden !important;
    font-size:   14px !important;
    font-weight: 700 !important;
    font-family: 'SF Mono','Fira Code','Courier New',monospace !important;
    letter-spacing: .02em !important;
    line-height: 1.5 !important;
    padding-top: 9px !important;
}
/* hide the resize handle and extra chrome */
.sym-input-wrap [data-testid="stTextArea"] > label { display:none; }
.sym-input-wrap [data-testid="stTextArea"] > div > div { padding: 0 !important; }

/* ── Confirmed text cells (normal size) ─────────────────── */
.sym-cell {
    font-size: 13px !important;
    line-height: 1.35 !important;
    padding: 4px 0 !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}
.sym-cell-meta {
    font-size: 12px !important;
    opacity: .72 !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}

/* ── Symbol chip button ─────────────────────────────────── */
.sym-chip button {
    border: 1.5px solid rgba(49,51,63,.18) !important;
    border-radius: 5px !important;
    background: var(--secondary-background-color) !important;
    font-family: 'SF Mono','Fira Code','Courier New',monospace !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    padding: 3px 10px !important;
    color: var(--text-color) !important;
    width: 100%;
    min-height: unset !important;
}
.sym-chip button:hover {
    border-color: #0077c7 !important;
    color: #0077c7 !important;
}
[data-theme="dark"] .sym-chip button:hover { color: #55aaff !important; }

/* ── Status badge ───────────────────────────────────────── */
.badge-ok  { color: #1e8a44; font-weight: 600; font-size: 13px; }
.badge-err { color: #c0392b; font-size: 12px; }
.badge-srch{ opacity: .55; font-size: 12px; }
[data-theme="dark"] .badge-ok  { color: #4caf80; }
[data-theme="dark"] .badge-err { color: #ef5b5b; }

/* ── Suggestion dropdown ────────────────────────────────── */
.sug-list {
    border: 1px solid rgba(49,51,63,.13);
    border-top: none;
    border-radius: 0 0 7px 7px;
    overflow: hidden;
    box-shadow: 0 4px 14px rgba(0,0,0,.11);
    background: var(--background-color);
    margin-top: -2px;
}
[data-theme="dark"] .sug-list {
    border-color: rgba(250,250,250,.13);
    box-shadow: 0 4px 14px rgba(0,0,0,.32);
}
.sug-div {
    border: none;
    border-top: 1px solid rgba(49,51,63,.06);
    margin: 0;
}
[data-theme="dark"] .sug-div { border-top-color: rgba(250,250,250,.06); }

.sug-item button {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    text-align: left !important;
    padding: 7px 10px 3px !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    font-family: 'SF Mono','Fira Code','Courier New',monospace !important;
    min-height: unset !important;
    width: 100%;
}
.sug-item button:hover { background: rgba(0,119,199,.08) !important; }

.sug-name {
    font-size: 10.5px !important;
    opacity: .55 !important;
    margin: 0 !important;
    padding: 0 10px 5px !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    display: block;
}

/* ── Icon buttons (del / cancel) ────────────────────────── */
.icon-btn button {
    background: transparent !important;
    border: none !important;
    color: rgba(49,51,63,.32) !important;
    font-size: 13px !important;
    padding: 2px 4px !important;
    min-height: unset !important;
}
.icon-btn button:hover {
    color: #c0392b !important;
    background: rgba(192,57,43,.08) !important;
}

/* ── Add-row button: flush against the table ────────────── */
.add-row-btn {
    margin-top: -1px !important;  /* overlap the last row border */
}
.add-row-btn button {
    width: 100% !important;
    border: 1.5px dashed rgba(49,51,63,.2) !important;
    border-radius: 0 0 8px 8px !important;
    border-top: none !important;
    background: transparent !important;
    font-size: 22px !important;
    font-weight: 300 !important;
    color: rgba(49,51,63,.38) !important;
    padding: 5px 0 !important;
    min-height: unset !important;
}
.add-row-btn button:hover {
    border-color: #0077c7 !important;
    color: #0077c7 !important;
    background: rgba(0,119,199,.06) !important;
}
[data-theme="dark"] .add-row-btn button {
    border-color: rgba(250,250,250,.18) !important;
    color: rgba(250,250,250,.38) !important;
}

/* ── Tighten column padding ─────────────────────────────── */
.sym-table-area [data-testid="column"] {
    padding-left:  3px !important;
    padding-right: 3px !important;
}
</style>
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_row(inp: str = "") -> dict:
    rid = st.session_state.get("_sym_rid", 0)
    st.session_state["_sym_rid"] = rid + 1
    return dict(id=rid, confirmed=False, symbol=inp,
                name="", exchange="", country="",
                prev=None, searching=False, not_found=False)


def _sug_key(rid: int) -> str:  return f"_sug_{rid}"
def _inp_key(rid: int) -> str:  return f"sym_ta_{rid}"


def _tokenize(raw: str) -> list[str]:
    s = re.sub(r'["\u2018\u2019\u201c\u201d\u300c\u300d\']', ' ', raw)
    s = re.sub(r'[,\u3001\u3002;|\t\r\n]+', ' ', s)
    out = []
    for t in s.split():
        t = re.sub(r'^[^A-Za-z0-9\^]', '', t)
        t = re.sub(r'[^A-Za-z0-9.\-\^]$', '', t)
        t = t.upper()
        if t and re.match(r'^[A-Z0-9\^][A-Z0-9.\-\^]*$', t):
            out.append(t)
    return out


def _is_bulk(raw: str) -> bool:
    """True when raw contains any separator or multiple space-separated tokens."""
    return (bool(re.search(r'[,\u3001\u3002;|\n\r\t]', raw))
            or len(raw.split()) > 1)


def _confirmed_symbols() -> set[str]:
    return {r["symbol"].upper()
            for r in st.session_state.get("ticker_rows", [])
            if r.get("confirmed")}


def _confirm(row: dict, hit: dict) -> None:
    row.update(confirmed=True, symbol=hit["symbol"],
               name=hit.get("name",""), exchange=hit.get("exchange",""),
               country=hit.get("country",""),
               not_found=False, searching=False, prev=None)


def _handle_bulk(src_rid: int, toks: list[str], country: str) -> None:
    """Replace source row with one confirmed row per unique token."""
    rows = st.session_state.ticker_rows
    idx  = next((i for i, r in enumerate(rows) if r["id"] == src_rid), None)
    if idx is None:
        return

    already = _confirmed_symbols()
    new_rows: list[dict] = []
    dupes:    list[str]  = []

    for tok in toks:
        if tok in already:
            dupes.append(tok)
            continue
        r   = _new_row(tok)
        hit = best_match(tok, country)
        if hit:
            sym = hit["symbol"].upper()
            if sym in already or sym in {nr["symbol"].upper()
                                         for nr in new_rows if nr["confirmed"]}:
                dupes.append(tok)
                continue
            _confirm(r, hit)
        else:
            r["not_found"] = True
        new_rows.append(r)
        if r.get("confirmed"):
            already.add(r["symbol"].upper())

    if not new_rows:
        new_rows.append(_new_row())

    rows[idx : idx + 1] = new_rows
    st.session_state.ticker_rows = rows

    if dupes:
        st.session_state["_dup_notice"] = dupes


# ── Main render ────────────────────────────────────────────────────────────────

def render_symbol_table(labels: dict) -> None:
    T       = lambda k: labels.get(k, k)  # noqa: E731
    country = st.session_state.get("user_country", "JP")

    st.markdown(_CSS, unsafe_allow_html=True)

    # Duplicate toast (set by bulk handler)
    dupes = st.session_state.pop("_dup_notice", [])
    if dupes:
        st.toast(
            f"⚠️ {', '.join(dupes)} — "
            + (T("msg_duplicate") or "重複のため除外されました"),
            icon="⚠️",
        )

    rows: list[dict] = st.session_state.setdefault("ticker_rows", [])
    if not rows:
        rows.append(_new_row())

    needs_rerun = False

    # ── Header ───────────────────────────────────────────────────────────
    st.markdown('<div class="sym-table-area">', unsafe_allow_html=True)
    hdr = st.columns(_COLS)
    for col, label in zip(hdr, [
        T("col_symbol"), T("col_name"), T("col_exchange"),
        T("col_country"), T("col_status"), "",
    ]):
        col.markdown(f'<p class="sym-th">{label}</p>', unsafe_allow_html=True)
    st.markdown('<hr class="sym-sep-heavy">', unsafe_allow_html=True)

    # ── Rows ──────────────────────────────────────────────────────────────
    to_delete: list[int] = []

    for i, row in enumerate(rows):
        rid = row["id"]
        if i > 0:
            st.markdown('<hr class="sym-sep">', unsafe_allow_html=True)

        if row["confirmed"]:
            act = _render_confirmed(row, T)
        else:
            act = _render_edit(row, T, country)

        if act == "edit":
            row["prev"]      = {k: row[k] for k in ("symbol","name","exchange","country")}
            row["confirmed"] = False
            needs_rerun      = True
        elif act == "delete":
            to_delete.append(rid)
            needs_rerun = True
        elif act == "cancel":
            if row.get("prev"):
                row.update(**row["prev"], confirmed=True,
                           searching=False, not_found=False, prev=None)
                st.session_state[_sug_key(rid)] = []
            needs_rerun = True
        elif act == "confirmed":
            st.session_state[_sug_key(rid)] = []
            needs_rerun = True

    st.markdown('</div>', unsafe_allow_html=True)

    if to_delete:
        st.session_state.ticker_rows = [r for r in rows if r["id"] not in to_delete]
        if not st.session_state.ticker_rows:
            st.session_state.ticker_rows.append(_new_row())
        needs_rerun = True

    # ── Add button ─────────────────────────────────────────────────────────
    st.markdown('<div class="add-row-btn">', unsafe_allow_html=True)
    if st.button("＋", key="sym_add", help=T("btn_add_symbol"),
                 use_container_width=True):
        st.session_state.ticker_rows.append(_new_row())
        needs_rerun = True
    st.markdown('</div>', unsafe_allow_html=True)

    if needs_rerun:
        st.rerun()


# ── Confirmed row ─────────────────────────────────────────────────────────────

def _render_confirmed(row: dict, T) -> str:
    rid  = row["id"]
    cols = st.columns(_COLS)

    with cols[0]:
        st.markdown('<div class="sym-chip">', unsafe_allow_html=True)
        if st.button(row["symbol"], key=f"chip_{rid}",
                     help=T("hint_dblclick"), use_container_width=True):
            return "edit"
        st.markdown("</div>", unsafe_allow_html=True)

    cols[1].markdown(
        f'<p class="sym-cell">{row.get("name","")}</p>', unsafe_allow_html=True)
    cols[2].markdown(
        f'<p class="sym-cell-meta">{row.get("exchange","")}</p>', unsafe_allow_html=True)
    cols[3].markdown(
        f'<p class="sym-cell-meta">{row.get("country","")}</p>', unsafe_allow_html=True)
    cols[4].markdown(
        f'<p class="badge-ok">✓ {T("status_confirmed_short")}</p>',
        unsafe_allow_html=True)

    with cols[5]:
        st.markdown('<div class="icon-btn">', unsafe_allow_html=True)
        if st.button("✕", key=f"del_{rid}"):
            return "delete"
        st.markdown("</div>", unsafe_allow_html=True)

    return ""


# ── Edit row ──────────────────────────────────────────────────────────────────

def _render_edit(row: dict, T, country: str) -> str:
    rid         = row["id"]
    sug_key     = _sug_key(rid)
    inp_key     = _inp_key(rid)
    suggestions = st.session_state.get(sug_key, [])
    has_prev    = bool(row.get("prev"))

    cols = st.columns(_COLS)

    with cols[0]:

        # ── on_change callback ────────────────────────────────────────────
        def _on_change(rid=rid, country=country):
            raw = (st.session_state.get(_inp_key(rid)) or "").strip()
            r   = next((x for x in st.session_state.ticker_rows
                        if x["id"] == rid), None)
            if not r:
                return

            if not raw:
                st.session_state[_sug_key(rid)] = []
                r["not_found"] = False
                return

            # ── Bulk paste ────────────────────────────────────────────────
            if _is_bulk(raw):
                toks = _tokenize(raw)
                if len(toks) > 1:
                    _handle_bulk(rid, toks, country)
                    return

            # ── Single symbol ─────────────────────────────────────────────
            r["symbol"]    = raw.upper()
            r["searching"] = True
            results = search_suggestions(raw.upper(), country)
            r["searching"] = False

            if not results:
                r["not_found"] = True
                st.session_state[_sug_key(rid)] = []
                return

            r["not_found"] = False
            st.session_state[_sug_key(rid)] = results

            # Auto-confirm exact match
            top = results[0]
            if top["symbol"].upper() == raw.upper():
                # Check duplicate
                already = {x["symbol"].upper()
                           for x in st.session_state.ticker_rows
                           if x["confirmed"] and x["id"] != rid}
                if top["symbol"].upper() in already:
                    r["not_found"]  = True
                    st.session_state["_dup_notice"] = [top["symbol"]]
                    st.session_state[_sug_key(rid)] = []
                else:
                    _confirm(r, top)
                    st.session_state[_sug_key(rid)] = []

        # ── text_area (captures multi-line paste) ─────────────────────────
        current = st.session_state.get(inp_key, row.get("symbol", "") or "")
        st.markdown('<div class="sym-input-wrap">', unsafe_allow_html=True)
        st.text_area(
            label            = T("col_symbol"),
            value            = current,
            key              = inp_key,
            placeholder      = T("placeholder_symbol"),
            label_visibility = "collapsed",
            on_change        = _on_change,
            height           = 42,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        if row.get("not_found"):
            st.markdown(
                f'<p class="badge-err">{T("status_not_found")}</p>',
                unsafe_allow_html=True)

        # ── Suggestion dropdown ────────────────────────────────────────────
        if suggestions:
            already = {x["symbol"].upper()
                       for x in st.session_state.ticker_rows
                       if x["confirmed"] and x["id"] != rid}
            st.markdown('<div class="sug-list">', unsafe_allow_html=True)
            shown = 0
            for j, sug in enumerate(suggestions[:8]):
                if sug["symbol"].upper() in already:
                    continue  # skip duplicates in suggestions
                if shown > 0:
                    st.markdown('<hr class="sug-div">', unsafe_allow_html=True)
                st.markdown('<div class="sug-item">', unsafe_allow_html=True)
                if st.button(sug["symbol"], key=f"sug_{rid}_{j}",
                             use_container_width=True):
                    _confirm(row, sug)
                    st.session_state[sug_key] = []
                    return "confirmed"
                st.markdown("</div>", unsafe_allow_html=True)

                name = sug.get("name", "")
                tag  = sug.get("exchange") or sug.get("country") or ""
                display = (name[:22] + "…" if len(name) > 22 else name)
                if tag:
                    display += f"  [{tag}]"
                st.markdown(
                    f'<span class="sug-name">{display}</span>',
                    unsafe_allow_html=True)
                shown += 1
            st.markdown("</div>", unsafe_allow_html=True)

    # Status column: cancel for re-edit
    with cols[4]:
        if has_prev:
            st.markdown('<div class="icon-btn">', unsafe_allow_html=True)
            if st.button("↩", key=f"cancel_{rid}",
                         help=T("hint_cancel_edit") or "編集をキャンセル"):
                return "cancel"
            st.markdown("</div>", unsafe_allow_html=True)

    with cols[5]:
        st.markdown('<div class="icon-btn">', unsafe_allow_html=True)
        if st.button("✕", key=f"del_{rid}"):
            return "delete"
        st.markdown("</div>", unsafe_allow_html=True)

    return ""