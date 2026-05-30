"""Standalone watchlist daemon: periodically scrape + score the watchlist and
email a sentiment report.

Run:
    phantom-bridge-watch            # loops forever using the configured interval
    phantom-bridge-watch --once     # run a single cycle and exit (handy for cron)

Configuration (Bright Data key, SMTP, recipient, interval) is read from the
`settings` table — set it in the dashboard's Settings tab.
"""

import argparse
import asyncio
import time
from datetime import datetime, timezone

from . import config, notify, report, sentiment, storage
from .scraper import run as scrape_run


def _resolve_api_key(conn) -> str | None:
    return storage.get_setting(conn, "bright_data_api_key") or config.get_api_key()


def _process_company(conn, company: str) -> list:
    """Scrape fresh events for a company, score any unscored, return scored rows."""
    api_key = _resolve_api_key(conn)
    num_results = int(storage.get_setting(conn, "watch_results", "5") or 5)
    events = asyncio.run(scrape_run(company, num_results=num_results, country="US", api_key=api_key))
    inserted, _ = storage.insert_events(conn, events)
    print(f"[watch]   {company}: scraped, {inserted} new events")

    now = datetime.now(timezone.utc).isoformat()
    scored_now = 0
    for r in storage.fetch_scored_events(conn, company):
        if r["sentiment"] is None:
            s = sentiment.score_text(sentiment.event_text(r["title"], r["description"]))
            if s:
                storage.write_enrichment(
                    conn, r["id"], model_version=sentiment.MODEL_VERSION, analyzed_at=now, **s
                )
                scored_now += 1
    print(f"[watch]   {company}: scored {scored_now} new items")
    return storage.fetch_scored_events(conn, company)


def run_once(conn) -> None:
    companies = storage.list_watchlist(conn)
    if not companies:
        print("[watch] watchlist is empty; nothing to do")
        return

    per_company = []
    for company in companies:
        meta = storage.get_company(conn, company)
        scored = _process_company(conn, company)
        per_company.append({
            "company": company,
            "ticker": meta["ticker"] if meta else None,
            "exchange": meta["exchange"] if meta else None,
            "scored": scored,
        })

    subject, html = report.build_email(per_company)

    s = storage.get_settings(conn)
    recipient = s.get("email_to")
    host = s.get("smtp_host")
    if not (recipient and host):
        print("[watch] email not configured (need smtp_host + email_to); report not sent")
        return

    notify.send_email(
        host=host,
        port=s.get("smtp_port") or 587,
        username=s.get("smtp_user"),
        password=s.get("smtp_password"),
        sender=s.get("email_from") or s.get("smtp_user") or recipient,
        recipient=recipient,
        subject=subject,
        html_body=html,
    )
    print(f"[watch] emailed report to {recipient}")


def main() -> None:
    parser = argparse.ArgumentParser(description="phantom-bridge watchlist daemon")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    conn = storage.connect()
    storage.init_db(conn)

    if args.once:
        run_once(conn)
        return

    interval_h = float(storage.get_setting(conn, "watch_interval_hours", "24") or 24)
    print(f"[watch] starting; interval={interval_h}h; watchlist={storage.list_watchlist(conn)}")
    try:
        while True:
            run_once(conn)
            print(f"[watch] sleeping {interval_h}h…")
            time.sleep(interval_h * 3600)
    except KeyboardInterrupt:
        print("\n[watch] stopped")


if __name__ == "__main__":
    main()
