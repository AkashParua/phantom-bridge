"""Run the prompt library against Bright Data's Discover API.

Substitutes a company name into each prompt, runs Discover for every selected
signal, and normalizes the results into event records.

A "selection" controls which signals run and how many results each returns:
  * ``signal_results=None``      -> all signals, each at ``num_results``.
  * ``signal_results={sig: n}``  -> only those signals, each at its own ``n``.
"""

import asyncio
from datetime import datetime, timezone

from brightdata import BrightDataClient

from .config import get_api_key
from .events import build_event
from .prompts import load_prompts


def _selected_prompts(signal_results: dict | None, num_results: int) -> list[tuple[dict, int]]:
    """Return [(prompt, n_results), ...] for the chosen signals.

    ``signal_results=None`` -> every prompt at ``num_results``; a dict -> only the
    listed signals, each at its mapped count.
    """
    prompts = load_prompts()
    if signal_results is not None:
        return [(p, int(signal_results[p["signal"]])) for p in prompts if p["signal"] in signal_results]
    return [(p, num_results) for p in prompts]


async def run(company: str, num_results: int = 5, country: str = "US",
              api_key: str | None = None, *, signal_results: dict | None = None) -> list[dict]:
    api_key = api_key or get_api_key()
    if not api_key:
        raise RuntimeError(
            "No Bright Data API key. Set it in the dashboard Settings tab or in .env."
        )

    work = _selected_prompts(signal_results, num_results)
    print(f"Running {len(work)} prompts. Searching for: {company}\n")

    scraped_at = datetime.now(timezone.utc).isoformat()
    events: list[dict] = []

    async with BrightDataClient(token=api_key, auto_create_zones=False) as client:
        for i, (p, n) in enumerate(work, 1):
            query = p["query"].format(company=company)
            print(f"[{i}/{len(work)}] {p['category']} — {p['signal']} (n={n})")
            try:
                result = await client.discover(
                    include_content=True,
                    query=query,
                    intent=p["intent"].format(company=company),
                    country=country,
                    num_results=n,
                    filter_keywords=[company],
                )
                for r in (result.data or []):
                    events.append(build_event(
                        r, company=company, category=p["category"],
                        signal=p["signal"], query=query, scraped_at=scraped_at,
                    ))
            except Exception as exc:  # keep going across signals
                print(f"    ERROR: {type(exc).__name__}: {exc}")

    print(f"Built {len(events)} events.")
    return events


def run_iter(company: str, country: str = "US", api_key: str | None = None, *,
             signal_results: dict | None = None, num_results: int = 5):
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

    work = _selected_prompts(signal_results, num_results)
    scraped_at = datetime.now(timezone.utc).isoformat()

    async def _fetch(p: dict, query: str, n: int):
        async with BrightDataClient(token=api_key, auto_create_zones=False) as client:
            result = await client.discover(
                include_content=True,
                query=query,
                intent=p["intent"].format(company=company),
                country=country,
                num_results=n,
                filter_keywords=[company],
            )
        return result.data or []

    total = len(work)
    for i, (p, n) in enumerate(work, 1):
        query = p["query"].format(company=company)
        events: list[dict] = []
        error = None
        try:
            rows = asyncio.run(_fetch(p, query, n))
            events = [
                build_event(r, company=company, category=p["category"],
                            signal=p["signal"], query=query, scraped_at=scraped_at)
                for r in rows
            ]
        except Exception as exc:  # surface per-prompt, keep going
            error = f"{type(exc).__name__}: {exc}"
        yield {
            "index": i, "total": total, "category": p["category"],
            "signal": p["signal"], "events": events, "error": error,
        }
