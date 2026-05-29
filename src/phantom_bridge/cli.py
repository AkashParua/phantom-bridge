"""Command-line entry point: scrape disruption signals and persist them."""

import argparse
import asyncio

from . import storage
from .config import DEFAULT_DB
from .scraper import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Run phantom-bridge disruption prompts.")
    parser.add_argument("company", nargs="?", default="ARAMCO", help="Target company name")
    parser.add_argument("--results", type=int, default=5, help="Results per query")
    parser.add_argument("--country", default="US", help="2-letter ISO country code")
    parser.add_argument("--db", default=None, help=f"SQLite path (default: {DEFAULT_DB})")
    parser.add_argument("--no-store", action="store_true", help="Run without writing to the DB")
    args = parser.parse_args()

    events = asyncio.run(run(args.company, args.results, args.country))

    if args.no_store:
        return
    conn = storage.connect(args.db or DEFAULT_DB)
    storage.init_db(conn)
    inserted, skipped = storage.insert_events(conn, events)
    conn.close()
    print(f"DB: inserted {inserted} new, skipped {skipped} (duplicate or link-less).")


if __name__ == "__main__":
    main()
