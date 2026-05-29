"""Best-effort extraction of a publish date from a Discover API result."""

import re
from datetime import date

# Keys that genuinely carry a *publish* date. Deliberately excludes "timestamp"
# and "datetime" — on the Discover API those hold the CRAWL time (when we fetched
# the page), not when the content was published.
_PUBLISH_DATE_KEYS = (
    "published_at", "published", "pub_date", "publish_date",
    "date", "last_updated", "updated", "modified",
)

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _iso(year: int, month: int, day: int) -> str | None:
    """Return an ISO date string, or None if the y/m/d is not a real date."""
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_date_text(text: str | None) -> str | None:
    """Find the first plausible date in free text and normalize it to ISO (YYYY-MM-DD)."""
    if not text:
        return None
    # ISO: 2026-02-25 (optionally followed by a time component, e.g. T10:30:00Z)
    m = re.search(r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)", text)
    if m and (iso := _iso(int(m[1]), int(m[2]), int(m[3]))):
        return iso
    # Month DD, YYYY: "March 2, 2026" / "Mar 2 2026"
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})\b", text)
    if m and m[1].lower() in _MONTHS and (iso := _iso(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))):
        return iso
    # DD Month YYYY: "25 February 2026"
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(20\d{2})\b", text)
    if m and m[2].lower() in _MONTHS and (iso := _iso(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))):
        return iso
    # MM/DD/YYYY (US-ordered, since the API defaults to country=US)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if m and (iso := _iso(int(m[3]), int(m[1]), int(m[2]))):
        return iso
    return None


def extract_published_at(row: dict) -> tuple[str | None, str | None]:
    """Best-effort publish date for a result, returned as (iso_date, source).

    Sources are tried most-reliable first. On the Discover API the SERP-style
    ``description`` snippet is prefixed with the publish date (e.g. "Mar 2, 2026 — ..."),
    which is the strongest signal; the ``timestamp`` field is the crawl time and is
    intentionally never used here.
    """
    # 1. Leading date in the SERP description snippet — most reliable for news.
    if iso := _parse_date_text(row.get("description")):
        return iso, "description"
    # 2. Date embedded in the URL slug, e.g. /2026/02/25/ or -2026-02-25/.
    link = row.get("link") or ""
    m = re.search(r"(?:^|[/_-])(20\d{2})[/_-](\d{1,2})[/_-](\d{1,2})(?:[/_-]|$)", link)
    if m and (iso := _iso(int(m[1]), int(m[2]), int(m[3]))):
        return iso, "url"
    # 3. Explicit publish-date keys, if the API ever supplies one (not "timestamp").
    for key in _PUBLISH_DATE_KEYS:
        if (val := row.get(key)) and (iso := _parse_date_text(str(val))):
            return iso, f"metadata:{key}"
    # 4. First date in the title.
    if iso := _parse_date_text(row.get("title")):
        return iso, "title"
    # 5. Last resort: first date in the page body (often noisy boilerplate).
    if iso := _parse_date_text((row.get("content") or "")[:5000]):
        return iso, "content"
    return None, None
