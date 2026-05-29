"""Normalize raw Discover API results into downstream-ready event records."""

import hashlib

from .dates import extract_published_at


def build_event(row: dict, *, company: str, category: str, signal: str, query: str, scraped_at: str) -> dict:
    """Normalize a raw Discover result into a downstream-ready event record."""
    link = row.get("link") or ""
    content = row.get("content")
    fingerprint = (link or (row.get("title") or "")) + (content or "")
    published_at, published_at_source = extract_published_at(row)
    try:
        relevance_score = float(row["relevance_score"])
    except (KeyError, TypeError, ValueError):
        relevance_score = None
    return {
        "company": company,
        "category": category,
        "signal": signal,
        "query": query,
        "title": row.get("title"),
        "link": link or None,
        "description": row.get("description"),
        "content": content,
        "relevance_score": relevance_score,
        "published_at": published_at,
        "published_at_source": published_at_source,
        "scraped_at": scraped_at,
        "crawled_at": row.get("timestamp"),
        "content_hash": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
        "raw": row,
    }
