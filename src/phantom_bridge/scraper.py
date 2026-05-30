"""Run the prompt library against Bright Data's Discover API.

Substitutes a company name into each prompt, runs Discover for every signal,
and normalizes the results into event records.
"""

import asyncio
from datetime import datetime, timezone

from brightdata import BrightDataClient

from .config import get_api_key
from .events import build_event
from .prompts import load_prompts


async def run(company: str, num_results: int, country: str, api_key: str | None = None) -> list[dict]:
    api_key = api_key or get_api_key()
    if not api_key:
        raise RuntimeError(
            "No Bright Data API key. Set it in the dashboard Settings tab or in .env."
        )

    prompts = load_prompts()
    print(f"Loaded {len(prompts)} prompts. Searching for: {company}\n")

    scraped_at = datetime.now(timezone.utc).isoformat()
    events: list[dict] = []

    async with BrightDataClient(token=api_key, auto_create_zones=False) as client:
        for i, p in enumerate(prompts, 1):
            query = p["query"].format(company=company)
            print(f"[{i}/{len(prompts)}] {p['category']} — {p['signal']}")
            print(f"    query: {query}")
            try:
                result = await client.discover(
                    include_content=True,
                    query=query,
                    intent=p["intent"].format(company=company),
                    country=country,
                    num_results=num_results,
                    filter_keywords=[company],  # require the company to appear in every result
                )
                rows = result.data or []
                if not rows:
                    print("    (no results)\n")
                    continue
                for r in rows:
                    event = build_event(
                        r,
                        company=company,
                        category=p["category"],
                        signal=p["signal"],
                        query=query,
                        scraped_at=scraped_at,
                    )
                    events.append(event)
                    print(f"    [{event['relevance_score']}] {event['title']}")
                    print(f"          {event['link']}")
                    print(f"          published_at: {event['published_at']} (via {event['published_at_source']})")
                print()
            except Exception as exc:  # keep going across signals
                print(f"    ERROR: {type(exc).__name__}: {exc}\n")

    print(f"Built {len(events)} events.")
    return events


def run_iter(company: str, num_results: int, country: str, api_key: str | None = None):
    """Sync generator that yields one result per prompt as its Discover call completes.

    Lets a UI render incrementally (show each request as it finishes, links clickable
    right away) instead of waiting for all prompts. Each yielded dict has:
    ``{index, total, category, signal, events, error}``.
    """
    api_key = api_key or get_api_key()
    if not api_key:
        raise RuntimeError(
            "No Bright Data API key. Set it in the dashboard Settings tab or in .env."
        )

    prompts = load_prompts()
    scraped_at = datetime.now(timezone.utc).isoformat()

    async def _fetch(p: dict, query: str):
        async with BrightDataClient(token=api_key, auto_create_zones=False) as client:
            result = await client.discover(
                include_content=True,
                query=query,
                intent=p["intent"].format(company=company),
                country=country,
                num_results=num_results,
                filter_keywords=[company],
            )
        return result.data or []

    for i, p in enumerate(prompts, 1):
        query = p["query"].format(company=company)
        events: list[dict] = []
        error = None
        try:
            rows = asyncio.run(_fetch(p, query))
            events = [
                build_event(r, company=company, category=p["category"],
                            signal=p["signal"], query=query, scraped_at=scraped_at)
                for r in rows
            ]
        except Exception as exc:  # surface per-prompt, keep going
            error = f"{type(exc).__name__}: {exc}"
        yield {
            "index": i, "total": len(prompts), "category": p["category"],
            "signal": p["signal"], "events": events, "error": error,
        }
