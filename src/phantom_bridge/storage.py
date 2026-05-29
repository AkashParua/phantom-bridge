"""SQLite persistence layer for phantom-bridge disruption events.

Design:
  * Surrogate integer PK (``events.id``) — stable FK target for ``enrichment``.
  * Dedup via ``UNIQUE(company, link)`` with INSERT OR IGNORE — the URL is the
    stable identity of a result, so re-runs are idempotent and the first signal
    that surfaces an article wins.
  * ``published_at`` is indexed for downstream date filtering / time-series joins.
  * Raw analysis is kept separate from derived analysis: scraped data lands in
    ``events`` and is never mutated; sentiment / financial / prediction outputs go
    in ``enrichment`` keyed by ``event_id`` (re-runnable per ``model_version``).
"""

import json
import sqlite3
from pathlib import Path

from .config import DEFAULT_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    company             TEXT NOT NULL,
    category            TEXT,
    signal              TEXT,
    query               TEXT,
    title               TEXT,
    link                TEXT NOT NULL,
    description         TEXT,
    content             TEXT,
    relevance_score     REAL,
    published_at        TEXT,
    published_at_source TEXT,
    scraped_at          TEXT,
    crawled_at          TEXT,
    content_hash        TEXT,
    raw_json            TEXT,
    first_seen_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(company, link)
);

CREATE INDEX IF NOT EXISTS idx_events_published_at      ON events(published_at);
CREATE INDEX IF NOT EXISTS idx_events_company_published ON events(company, published_at);
CREATE INDEX IF NOT EXISTS idx_events_signal            ON events(signal);
CREATE INDEX IF NOT EXISTS idx_events_content_hash      ON events(content_hash);

CREATE TABLE IF NOT EXISTS enrichment (
    event_id            INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
    sentiment           REAL,
    sentiment_label     TEXT,
    financial_score     REAL,
    predicted_direction TEXT,
    confidence          REAL,
    model_version       TEXT,
    analyzed_at         TEXT
);

CREATE TABLE IF NOT EXISTS companies (
    name        TEXT PRIMARY KEY,
    ticker      TEXT,
    exchange    TEXT,
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS watchlist (
    company     TEXT PRIMARY KEY,
    added_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

# Columns populated on insert, in order. (id / first_seen_at are managed by SQLite.)
_INSERT_COLUMNS = (
    "company", "category", "signal", "query", "title", "link", "description",
    "content", "relevance_score", "published_at", "published_at_source",
    "scraped_at", "crawled_at", "content_hash", "raw_json",
)


def connect(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open (creating parent dirs as needed) a WAL-mode connection."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # readers don't block the writer
    conn.execute("PRAGMA foreign_keys=ON")    # enforce the enrichment FK
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't already exist."""
    conn.executescript(SCHEMA)
    conn.commit()


def insert_events(conn: sqlite3.Connection, events: list[dict]) -> tuple[int, int]:
    """Bulk-insert events, ignoring duplicates by (company, link).

    Returns (inserted, skipped) where skipped counts both duplicates and rows
    dropped for lacking a link (our dedup identity).
    """
    rows = []
    for e in events:
        if not e.get("link"):
            continue  # link is the dedup identity; a row without one is unusable
        rows.append((
            e["company"], e.get("category"), e.get("signal"), e.get("query"),
            e.get("title"), e["link"], e.get("description"), e.get("content"),
            e.get("relevance_score"), e.get("published_at"), e.get("published_at_source"),
            e.get("scraped_at"), e.get("crawled_at"), e.get("content_hash"),
            json.dumps(e.get("raw"), ensure_ascii=False) if e.get("raw") is not None else None,
        ))

    placeholders = ", ".join(["?"] * len(_INSERT_COLUMNS))
    sql = (
        f"INSERT OR IGNORE INTO events ({', '.join(_INSERT_COLUMNS)}) "
        f"VALUES ({placeholders})"
    )
    before = conn.total_changes
    conn.executemany(sql, rows)
    conn.commit()
    inserted = conn.total_changes - before
    skipped = len(events) - inserted
    return inserted, skipped


# --- Company metadata (ticker / exchange) -------------------------------------

def upsert_company(conn: sqlite3.Connection, name: str,
                   ticker: str | None = None, exchange: str | None = None) -> None:
    """Store (or update) a company's display metadata."""
    conn.execute(
        """
        INSERT INTO companies (name, ticker, exchange, updated_at)
        VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(name) DO UPDATE SET
            ticker     = excluded.ticker,
            exchange   = excluded.exchange,
            updated_at = excluded.updated_at
        """,
        (name, ticker, exchange),
    )
    conn.commit()


def get_company(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM companies WHERE name = ?", (name,)).fetchone()


# --- Dashboard reads ----------------------------------------------------------

def count_company_events(conn: sqlite3.Connection, company: str) -> int:
    """How many events are stored for a company (drives the hybrid cache check)."""
    return conn.execute(
        "SELECT COUNT(*) FROM events WHERE company = ?", (company,)
    ).fetchone()[0]


def fetch_scored_events(conn: sqlite3.Connection, company: str) -> list[sqlite3.Row]:
    """All of a company's events left-joined to their sentiment scores.

    ``sentiment`` is NULL for events not yet scored — the dashboard scores those,
    writes them via ``write_enrichment``, then re-reads.
    """
    return conn.execute(
        """
        SELECT e.id, e.title, e.description, e.link, e.signal, e.category,
               e.published_at, e.relevance_score,
               n.sentiment, n.sentiment_label, n.confidence, n.model_version
        FROM events e
        LEFT JOIN enrichment n ON n.event_id = e.id
        WHERE e.company = ?
        ORDER BY e.published_at DESC
        """,
        (company,),
    ).fetchall()


def write_enrichment(conn: sqlite3.Connection, event_id: int, *,
                     sentiment: float, sentiment_label: str, confidence: float,
                     model_version: str, analyzed_at: str) -> None:
    """Upsert a sentiment score for one event (re-runnable per model_version)."""
    conn.execute(
        """
        INSERT INTO enrichment (event_id, sentiment, sentiment_label, confidence,
                                model_version, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            sentiment       = excluded.sentiment,
            sentiment_label = excluded.sentiment_label,
            confidence      = excluded.confidence,
            model_version   = excluded.model_version,
            analyzed_at     = excluded.analyzed_at
        """,
        (event_id, sentiment, sentiment_label, confidence, model_version, analyzed_at),
    )
    conn.commit()


# --- Settings (key/value: API keys, SMTP config, interval) --------------------

def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    conn.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value),
    )
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


# --- Watchlist ----------------------------------------------------------------

def add_to_watchlist(conn: sqlite3.Connection, company: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO watchlist (company, added_at) "
        "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        (company,),
    )
    conn.commit()


def remove_from_watchlist(conn: sqlite3.Connection, company: str) -> None:
    conn.execute("DELETE FROM watchlist WHERE company = ?", (company,))
    conn.commit()


def list_watchlist(conn: sqlite3.Connection) -> list[str]:
    return [r["company"] for r in conn.execute("SELECT company FROM watchlist ORDER BY company")]
