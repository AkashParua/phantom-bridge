"""Build the HTML watchlist sentiment report emailed by the watcher."""

from html import escape

# Show at most this many (most-negative) events per company in the email.
_TOP_N = 8


def _summary(scored: list) -> tuple[int, int, int, float | None]:
    """(scored_count, negatives, positives, avg_sentiment) for one company."""
    have = [r for r in scored if r["sentiment"] is not None]
    if not have:
        return 0, 0, 0, None
    neg = sum(1 for r in have if r["sentiment_label"] == "negative")
    pos = sum(1 for r in have if r["sentiment_label"] == "positive")
    avg = sum(r["sentiment"] for r in have) / len(have)
    return len(have), neg, pos, avg


def _company_block(item: dict) -> str:
    company = item["company"]
    ticker = item.get("ticker")
    exchange = item.get("exchange")
    scored = item["scored"]

    n, neg, pos, avg = _summary(scored)
    head = " · ".join(p for p in (company, ticker, exchange) if p)
    avg_txt = f"{avg:+.2f}" if avg is not None else "—"

    have = [r for r in scored if r["sentiment"] is not None]
    top = sorted(have, key=lambda r: r["sentiment"])[:_TOP_N]
    rows = "".join(
        f"<tr>"
        f"<td>{escape(r['published_at'] or '')}</td>"
        f"<td style='text-align:right'>{r['sentiment']:+.2f}</td>"
        f"<td>{escape(r['sentiment_label'] or '')}</td>"
        f"<td>{escape(r['signal'] or '')}</td>"
        f"<td><a href='{escape(r['link'] or '')}'>{escape((r['title'] or '')[:90])}</a></td>"
        f"</tr>"
        for r in top
    )
    return (
        f"<h3 style='margin-bottom:2px'>{escape(head)}</h3>"
        f"<p style='margin-top:2px;color:#555'>{n} scored · avg {avg_txt} · "
        f"{neg} negative / {pos} positive</p>"
        f"<table border='1' cellpadding='5' cellspacing='0' "
        f"style='border-collapse:collapse;font-size:13px'>"
        f"<tr style='background:#f2f2f2'><th>date</th><th>score</th><th>label</th>"
        f"<th>signal</th><th>headline</th></tr>{rows}</table>"
    )


def build_email(per_company: list[dict]) -> tuple[str, str]:
    """Return (subject, html) for the watchlist report.

    `per_company` items: {"company", "ticker", "exchange", "scored"} where `scored`
    is a list of events left-joined with sentiment (rows support `r["key"]`).
    """
    total = sum(sum(1 for r in it["scored"] if r["sentiment"] is not None) for it in per_company)
    blocks = "".join(_company_block(it) for it in per_company)
    subject = (
        f"[phantom-bridge] watchlist report — "
        f"{len(per_company)} companies, {total} scored events"
    )
    html = (
        "<html><body style='font-family:sans-serif'>"
        "<h2>phantom-bridge — disruption sentiment report</h2>"
        f"{blocks if blocks else '<p>Watchlist is empty.</p>'}"
        "</body></html>"
    )
    return subject, html
