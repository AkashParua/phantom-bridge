"""Run the prompt library against Bright Data's Discover API.

Substitutes a company name into each prompt, runs Discover for every signal,
and normalizes the results into event records.
"""

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
