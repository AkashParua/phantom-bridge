# Project Structure

```
phantom-bridge/
├── pyproject.toml              # Package metadata, deps, `phantom-bridge` console script
├── requirements.txt            # Runtime deps (mirror of pyproject; prefer `pip install -e .`)
├── .env                        # BRIGHT_DATA_API_KEY (gitignored — never committed)
├── .env.example                # Template for .env
├── .gitignore
├── README.md                   # Project thesis: hyper-local supply-chain alpha
├── LICENSE
├── data/                       # SQLite DB lands here (gitignored)
│   └── phantom_bridge.db        #   created on first run
├── docs/
│   └── STRUCTURE.md            # This file
└── src/
    └── phantom_bridge/         # The installable package
        ├── __init__.py         # Package marker + __version__
        ├── __main__.py         # Enables `python -m phantom_bridge`
        ├── config.py           # Filesystem paths (DEFAULT_DB) + get_api_key()
        ├── cli.py              # argparse entry point; wires scraper → storage
        ├── scraper.py          # run(): the Discover API loop over all prompts
        ├── events.py           # build_event(): raw result → normalized event
        ├── dates.py            # extract_published_at(): publish-date parsing (pure)
        ├── sentiment.py        # score_text(): local distilRoBERTa sentiment scoring
        ├── notify.py           # send_email(): SMTP delivery (stdlib only)
        ├── report.py           # build_email(): HTML watchlist sentiment report
        ├── watcher.py          # `phantom-bridge-watch`: scheduled scrape→score→email daemon
        ├── storage.py          # SQLite layer: dedup insert, reads, settings, watchlist
        ├── prompts/            # Holistic company-news prompt library (packaged data)
        │   ├── __init__.py     #   load_prompts(): flatten all *.json into one list
        │   ├── financial_performance.json    # earnings, guidance, revenue
        │   ├── corporate_actions.json        # M&A, capital, restructuring
        │   ├── leadership_governance.json    # exec/board, insider, governance
        │   ├── legal_regulatory.json         # lawsuits, fines, approvals
        │   ├── operations_supply_chain.json  # facility/logistics/labor/incidents
        │   ├── products_partnerships.json    # launches/recalls, deals, expansion
        │   └── market_reputation.json        # analyst, stock moves, ESG/controversy
        └── dashboard/          # Streamlit sentiment dashboard (Phase 2)
            ├── __init__.py
            ├── app.py          #   UI: inputs → hybrid fetch → score → display
            └── launcher.py     #   `phantom-bridge-dashboard` console script
```

## Module responsibilities

| Module | Responsibility |
|--------|----------------|
| `config` | Filesystem paths and credential loading. No business logic. |
| `prompts` | Loading the prompt library (one JSON file per disruption category). |
| `dates` | Publish-date extraction from a result. Pure functions, no I/O. |
| `events` | Normalize a raw Discover result into a downstream-ready event dict. |
| `scraper` | Orchestration: substitute company into each prompt, call the API, build events. |
| `sentiment` | Local distilRoBERTa scoring of news text (offline; no LLM/API). |
| `notify` | SMTP email delivery (built-in `smtplib`). |
| `report` | Builds the HTML watchlist report (per-company summary + top events). |
| `watcher` | `phantom-bridge-watch` daemon: on an interval, scrape → score → email the watchlist. |
| `storage` | SQLite: dedup insert, dashboard reads, plus `enrichment`, `companies`, `settings`, `watchlist`. |
| `dashboard` | Streamlit UI (Analyze / Watchlist / Settings tabs). |
| `cli` | Argument parsing; runs the scraper, then persists. |

## Data flow

```
company name
   │
   ▼
prompts.load_prompts()         # 19 {signal, query, intent} specs
   │
   ▼
scraper.run()                  # for each prompt: Discover API call
   │   └── events.build_event() ── dates.extract_published_at()
   ▼
list[event dict]
   │
   ▼
storage.insert_events()        # dedup on (company, link), INSERT OR IGNORE
   │
   ▼
data/phantom_bridge.db
   ├── events       (raw scraped data — never mutated)
   ├── enrichment   (derived: sentiment scores; financial/prediction reserved)
   ├── companies    (ticker / exchange display metadata)
   ├── settings     (API keys, SMTP config, interval — key/value)
   └── watchlist    (companies the watcher monitors)
```

## Dashboard data flow (Phase 2)

```
submit (company, ticker, exchange, date)
   │
   ▼
storage.fetch_scored_events()      # events ⋈ enrichment for the company
   ├── cache hit  → score any unscored (sentiment.score_text) → display
   └── miss/force → scraper.run() → storage.insert_events() → score → display
```

## Entry points

```bash
phantom-bridge "ARAMCO" --results 3        # scraper console script (after `pip install -e .`)
python -m phantom_bridge "ARAMCO"          # module form
# Flags: --results N | --country XX | --db PATH | --no-store

pip install -e '.[dashboard]'              # install sentiment + UI deps
phantom-bridge-dashboard                   # launch the Streamlit dashboard
streamlit run src/phantom_bridge/dashboard/app.py   # equivalent

phantom-bridge-watch                       # watchlist daemon (loops on the configured interval)
phantom-bridge-watch --once                # one cycle then exit (handy for cron / Task Scheduler)
```
