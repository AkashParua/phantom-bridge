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

import asyncio
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from phantom_bridge import sentiment, storage, watcher
from phantom_bridge.scraper import run as scrape_run

st.set_page_config(page_title="phantom-bridge", layout="wide")

_LINK_COL = {"link": st.column_config.LinkColumn("link", display_text="open ↗")}


def _conn():
    conn = storage.connect()
    storage.init_db(conn)
    return conn


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


# --- Analyze tab --------------------------------------------------------------

def render_analyze(conn) -> None:
    with st.form("query"):
        c1, c2, c3 = st.columns(3)
        company = c1.text_input("Company", "ARAMCO")
        ticker = c2.text_input("Ticker", "")
        exchange = c3.text_input("Exchange", "")
        force = st.checkbox("Force re-scrape (calls Bright Data — slow, uses API credits)")
        submitted = st.form_submit_button("Analyze")

    # Scrape/score only on submit; remember the selection so date-filter reruns
    # (which happen outside the form) keep showing results.
    if submitted:
        if not company.strip():
            st.warning("Company is required.")
            return
        company = company.strip()
        storage.upsert_company(conn, company, ticker.strip() or None, exchange.strip() or None)

        # Hybrid cache + scrape: scrape only on a true miss, or when forced.
        if storage.count_company_events(conn, company) == 0 or force:
            api_key = storage.get_setting(conn, "bright_data_api_key")
            with st.spinner("Scraping Bright Data — this can take a few minutes…"):
                try:
                    events = asyncio.run(scrape_run(company, num_results=5, country="US", api_key=api_key))
                except Exception as exc:
                    st.error(f"Scrape failed: {exc}")
                    return
                inserted, _ = storage.insert_events(conn, events)
            st.success(f"Scraped and stored {inserted} new events.")

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

    # Date filter lives OUTSIDE the form, so toggling it takes effect immediately.
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

    cols = ["published_date", "sentiment", "sentiment_label", "confidence",
            "signal", "relevance_score", "title", "link"]
    st.dataframe(
        shown[cols].sort_values("published_date", ascending=False),
        use_container_width=True, hide_index=True, column_config=_LINK_COL,
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
    st.caption("Stored locally in the SQLite `settings` table (plaintext, gitignored).")

    with st.form("settings"):
        st.markdown("**Bright Data**")
        api_key = st.text_input("Bright Data API key", s.get("bright_data_api_key", ""), type="password")

        st.markdown("**Email (SMTP)**")
        c1, c2 = st.columns(2)
        smtp_host = c1.text_input("SMTP host", s.get("smtp_host", ""))
        smtp_port = c2.text_input("SMTP port", s.get("smtp_port", "587"))
        c3, c4 = st.columns(2)
        smtp_user = c3.text_input("SMTP username", s.get("smtp_user", ""))
        smtp_password = c4.text_input("SMTP password / app password", s.get("smtp_password", ""), type="password")
        c5, c6 = st.columns(2)
        email_from = c5.text_input("From email", s.get("email_from", ""))
        email_to = c6.text_input("Report recipient email", s.get("email_to", ""))

        st.markdown("**Schedule**")
        interval = st.text_input("Watch interval (hours)", s.get("watch_interval_hours", "24"))

        if st.form_submit_button("Save settings"):
            for key, val in {
                "bright_data_api_key": api_key, "smtp_host": smtp_host, "smtp_port": smtp_port,
                "smtp_user": smtp_user, "smtp_password": smtp_password, "email_from": email_from,
                "email_to": email_to, "watch_interval_hours": interval,
            }.items():
                storage.set_setting(conn, key, val.strip() or None)
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
