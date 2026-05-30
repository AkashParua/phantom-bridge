"""Minimalistic financial-news sentiment dashboard (Streamlit).

Three tabs:
  * Analyze   — score one company's news (hybrid cache + scrape).
  * Watchlist — manage the companies the watcher daemon monitors; run on demand.
  * Settings  — paste API keys, SMTP config, recipient email, and the interval.

Run:
    streamlit run src/phantom_bridge/dashboard/app.py
    # or, after `pip install -e '.[dashboard]'`:
    phantom-bridge-dashboard
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

# Ensure the src/ dir is importable when run as a bare script (e.g. Streamlit
# Community Cloud), where the package may not be pip-installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from phantom_bridge import sentiment, storage, watcher  # noqa: E402
from phantom_bridge.prompts import load_prompts  # noqa: E402
from phantom_bridge.scraper import run_iter  # noqa: E402

st.set_page_config(page_title="phantom-bridge", layout="wide")

_LINK_COL = {"link": st.column_config.LinkColumn("link", display_text="open ↗")}


def _conn():
    conn = storage.connect()
    storage.init_db(conn)
    return conn


def signal_selector(key_prefix: str, saved: dict | None = None) -> dict:
    """Category checkbox that reveals its per-signal controls when ticked.

    Selecting a category activates (reveals) its signals — each with an include
    checkbox and a results slider — instead of a click-to-open dropdown. Returns
    ``{signal: num_results}`` for the checked signals of *selected* categories.
    ``saved=None`` -> categories off by default; a dict -> categories holding any
    saved signal start on, with their sliders seeded. (Render OUTSIDE st.form.)
    """
    cats: dict[str, list] = {}
    for p in load_prompts():
        cats.setdefault(p["category"], []).append(p)

    selection: dict[str, int] = {}
    for cat, sigs in cats.items():
        cat_key = f"{key_prefix}_cat::{cat}"
        if cat_key not in st.session_state:
            st.session_state[cat_key] = bool(saved) and any(p["signal"] in saved for p in sigs)

        n_on = sum(1 for p in sigs if st.session_state.get(f"{key_prefix}_on::{p['signal']}", True))
        cat_on = st.checkbox(f"{cat.replace('_', ' ').title()}  ({n_on}/{len(sigs)})", key=cat_key)
        if not cat_on:
            continue

        with st.container(border=True):
            for p in sigs:
                sig = p["signal"]
                ck, nk = f"{key_prefix}_on::{sig}", f"{key_prefix}_n::{sig}"
                if ck not in st.session_state:
                    st.session_state[ck] = True if saved is None else (sig in saved)
                if nk not in st.session_state:
                    st.session_state[nk] = int(saved[sig]) if (saved and sig in saved) else 5
                c1, c2 = st.columns([3, 2])
                on = c1.checkbox(sig, key=ck)
                n = c2.slider("results", 1, 25, key=nk, label_visibility="collapsed")
                if on:
                    selection[sig] = n
    return selection


def _score_missing(conn, rows) -> int:
    """Score any events lacking a sentiment row; return how many were scored."""
    pending = [r for r in rows if r["sentiment"] is None]
    if not pending:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    progress = st.progress(0.0, text=f"Scoring {len(pending)} items…")
    for i, r in enumerate(pending, 1):
        scores = sentiment.score_text(sentiment.event_text(r["title"], r["description"]))
        if scores:
            storage.write_enrichment(
                conn, r["id"], model_version=sentiment.MODEL_VERSION, analyzed_at=now, **scores,
            )
        progress.progress(i / len(pending), text=f"Scoring {i}/{len(pending)}…")
    progress.empty()
    return len(pending)


def _to_frame(rows) -> pd.DataFrame:
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["published_date"] = pd.to_datetime(df["published_at"], errors="coerce").dt.date
    return df


_SENT_EMOJI = {"negative": "🔴", "positive": "🟢", "neutral": "⚪"}


def render_tiles(df: pd.DataFrame, per_row: int = 4) -> None:
    """Render results as a grid of clickable preview tiles, `per_row` per row."""
    records = df.to_dict("records")
    for start in range(0, len(records), per_row):
        cols = st.columns(per_row)
        for col, r in zip(cols, records[start:start + per_row]):
            with col.container(border=True, height=240):
                link = r.get("link") or ""
                title = (r.get("title") or link or "untitled")[:110]
                st.markdown(f"[**{title}**]({link})")

                label = r.get("sentiment_label")
                score = r.get("sentiment")
                if label:
                    badge = f"{_SENT_EMOJI.get(label, '')} {label}"
                    if score is not None:
                        badge += f" ({score:+.2f})"
                    st.caption(badge)

                domain = urlparse(link).netloc.replace("www.", "") if link else ""
                date = r.get("published_date")
                meta = " · ".join(x for x in (r.get("signal"), domain, str(date) if date else "") if x)
                if meta:
                    st.caption(meta)

                desc = (r.get("description") or "").strip()
                if desc:
                    st.write(desc[:130] + ("…" if len(desc) > 130 else ""))


# --- Analyze tab --------------------------------------------------------------

def render_analyze(conn) -> None:
    c1, c2, c3 = st.columns(3)
    company = c1.text_input("Company", "ARAMCO", key="an_company")
    ticker = c2.text_input("Ticker", "", key="an_ticker")
    exchange = c3.text_input("Exchange", "", key="an_exchange")
    st.markdown("**Signals to search** — tick a category to reveal its signals:")
    signal_results = signal_selector("an")
    force = st.checkbox("Force re-scrape (calls Bright Data — slow, uses API credits)", key="an_force")
    submitted = st.button("Analyze", type="primary")

    # Scrape/score only on submit; remember the selection so later reruns
    # (date filter, etc.) keep showing results.
    if submitted:
        if not company.strip():
            st.warning("Company is required.")
            return
        company = company.strip()
        storage.upsert_company(conn, company, ticker.strip() or None, exchange.strip() or None)

        # Hybrid cache + scrape: scrape only on a true miss, or when forced.
        if storage.count_company_events(conn, company) == 0 or force:
            if not signal_results:
                st.warning("Select at least one signal to search.")
                return
            api_key = storage.get_setting(conn, "bright_data_api_key")
            total_new = 0
            try:
                with st.status(f"Scraping {company} — {len(signal_results)} signals…", expanded=True) as status:
                    bar = st.progress(0.0)
                    for step in run_iter(company, country="US", api_key=api_key, signal_results=signal_results):
                        inserted, _ = storage.insert_events(conn, step["events"])
                        total_new += inserted
                        bar.progress(step["index"] / step["total"])
                        head = f"**[{step['index']}/{step['total']}] {step['category']} — {step['signal']}**"
                        if step["error"]:
                            status.markdown(f"{head} — ⚠️ {step['error']}")
                        elif step["events"]:
                            links = "\n".join(
                                f"- [{(e['title'] or e['link'])[:90]}]({e['link']})"
                                for e in step["events"] if e.get("link")
                            )
                            status.markdown(f"{head} — {len(step['events'])} results\n{links}")
                        else:
                            status.markdown(f"{head} — no results")
                    status.update(label=f"Scrape complete — {total_new} new events", state="complete")
            except Exception as exc:
                st.error(f"Scrape failed: {exc}")
                return

        _score_missing(conn, storage.fetch_scored_events(conn, company))
        st.session_state.analyzed = {
            "company": company, "ticker": ticker.strip(), "exchange": exchange.strip(),
        }

    sel = st.session_state.get("analyzed")
    if not sel:
        st.info("Enter a company and click **Analyze**.")
        return

    company = sel["company"]
    rows = storage.fetch_scored_events(conn, company)
    if not rows:
        st.warning("No events found for this company.")
        return

    df = _to_frame(rows)
    header = " · ".join(p for p in (company, sel["ticker"], sel["exchange"]) if p)
    st.subheader(header)

    use_dates = st.checkbox("Filter by publish date")
    start = end = None
    if use_dates:
        d1, d2 = st.columns(2)
        start = d1.date_input("From", value=None)
        end = d2.date_input("To", value=None)

    dated = df[df["published_date"].notna()].copy()
    undated = df[df["published_date"].isna()].copy()
    if use_dates and start:
        dated = dated[dated["published_date"] >= start]
    if use_dates and end:
        dated = dated[dated["published_date"] <= end]

    shown = dated
    scored = shown[shown["sentiment"].notna()]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Events", len(shown))
    m2.metric("Avg sentiment", f"{scored['sentiment'].mean():.3f}" if not scored.empty else "—")
    m3.metric("Negative", int((scored["sentiment_label"] == "negative").sum()))
    m4.metric("Positive", int((scored["sentiment_label"] == "positive").sum()))

    if not scored.empty:
        st.line_chart(scored.groupby("published_date")["sentiment"].mean(), height=220)

    ordered = shown.sort_values("published_date", ascending=False)
    view = st.radio("View", ["Tiles", "Table"], horizontal=True, label_visibility="collapsed")
    if view == "Tiles":
        render_tiles(ordered)
    else:
        cols = ["published_date", "sentiment", "sentiment_label", "confidence",
                "signal", "relevance_score", "title", "link"]
        st.dataframe(
            ordered[cols], use_container_width=True, hide_index=True, column_config=_LINK_COL,
        )

    if not undated.empty:
        with st.expander(f"Undated events ({len(undated)}) — no publish date parsed"):
            st.dataframe(
                undated[["sentiment", "sentiment_label", "signal", "title", "link"]],
                use_container_width=True, hide_index=True, column_config=_LINK_COL,
            )


# --- Watchlist tab ------------------------------------------------------------

def render_watchlist(conn) -> None:
    st.caption("Companies the watcher daemon (`phantom-bridge-watch`) scrapes, scores, "
               "and emails on a schedule.")

    with st.form("add_watch", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        company = c1.text_input("Company")
        ticker = c2.text_input("Ticker")
        exchange = c3.text_input("Exchange")
        if st.form_submit_button("Add to watchlist") and company.strip():
            storage.upsert_company(conn, company.strip(), ticker.strip() or None, exchange.strip() or None)
            storage.add_to_watchlist(conn, company.strip())
            st.success(f"Added {company.strip()}.")

    companies = storage.list_watchlist(conn)
    if not companies:
        st.info("Watchlist is empty.")
    else:
        for c in companies:
            meta = storage.get_company(conn, c)
            label = " · ".join(p for p in (c, meta["ticker"] if meta else None,
                                           meta["exchange"] if meta else None) if p)
            col1, col2 = st.columns([6, 1])
            col1.write(label)
            if col2.button("Remove", key=f"rm_{c}"):
                storage.remove_from_watchlist(conn, c)
                st.rerun()

    st.divider()
    if st.button("▶ Run watchlist now (scrape · score · email)", disabled=not companies):
        with st.spinner("Running the full watchlist cycle…"):
            try:
                watcher.run_once(conn)
                st.success("Cycle complete. If email is configured, a report was sent.")
            except Exception as exc:
                st.error(f"Run failed: {exc}")


# --- Settings tab -------------------------------------------------------------

def render_settings(conn) -> None:
    s = storage.get_settings(conn)
    saved_cfg = json.loads(s["signal_config"]) if s.get("signal_config") else None
    st.caption("Stored locally in the SQLite `settings` table (plaintext, gitignored).")

    st.markdown("**Bright Data**")
    api_key = st.text_input("Bright Data API key", s.get("bright_data_api_key", ""),
                            type="password", key="set_apikey")

    st.markdown("**Email (SMTP)**")
    c1, c2 = st.columns(2)
    smtp_host = c1.text_input("SMTP host", s.get("smtp_host", ""), key="set_host")
    smtp_port = c2.text_input("SMTP port", s.get("smtp_port", "587"), key="set_port")
    c3, c4 = st.columns(2)
    smtp_user = c3.text_input("SMTP username", s.get("smtp_user", ""), key="set_user")
    smtp_password = c4.text_input("SMTP password / app password", s.get("smtp_password", ""),
                                  type="password", key="set_pass")
    c5, c6 = st.columns(2)
    email_from = c5.text_input("From email", s.get("email_from", ""), key="set_from")
    email_to = c6.text_input("Report recipient email", s.get("email_to", ""), key="set_to")

    st.markdown("**Schedule**")
    interval = st.text_input("Watch interval (hours)", s.get("watch_interval_hours", "24"), key="set_interval")

    st.markdown("**Signals the watcher searches** — tick a category to reveal its signals:")
    watch_signal_results = signal_selector("set", saved=saved_cfg)

    if st.button("Save settings", type="primary"):
        for key, val in {
            "bright_data_api_key": api_key, "smtp_host": smtp_host, "smtp_port": smtp_port,
            "smtp_user": smtp_user, "smtp_password": smtp_password, "email_from": email_from,
            "email_to": email_to, "watch_interval_hours": interval,
        }.items():
            storage.set_setting(conn, key, val.strip() or None)
        storage.set_setting(conn, "signal_config", json.dumps(watch_signal_results))
        st.success("Settings saved. Restart `phantom-bridge-watch` to pick up a new interval.")


def main() -> None:
    st.title("phantom-bridge — company news sentiment")
    conn = _conn()
    analyze, watch, settings = st.tabs(["Analyze", "Watchlist", "Settings"])
    with analyze:
        render_analyze(conn)
    with watch:
        render_watchlist(conn)
    with settings:
        render_settings(conn)


if __name__ == "__main__":
    main()
