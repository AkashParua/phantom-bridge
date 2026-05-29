# phantom-bridge

**Alternative-data company intelligence.** Scrape holistic, real-time news about a public company from across the web, score each item for financial sentiment with a local model, and surface it in a minimal dashboard — with scheduled email reports.

## Why

In institutional finance, private equity, and corporate procurement, decision-makers are locked in a constant battle for *alpha* — an informational edge that lets them act before the broader market reacts. Traditional analysis leans on quarterly earnings, official filings, and structured market feeds. That data is reliable but **retrospective**: it tells you what happened months ago, not what is happening now.

To gain an edge, modern finance relies on **alternative data** — tracking real-world, operational activity to read a company's health before the official numbers are published. The catch is that this data is chaotic, unstructured, and scattered across millions of independent websites.

phantom-bridge collects **holistic company news** — financials, corporate actions, leadership, legal/regulatory, operations & supply chain, products, and market/reputation — resolves each item to the target company, scores its sentiment, and structures it into a clean, queryable, time-stamped record.

## Pipeline

```
company name
   │  Discover API (company-anchored prompt library, 7 categories)
   ▼
raw results ──► normalize (publish-date parse, dedup, raw JSON)  [events.py, dates.py]
   ▼
SQLite (dedup on company+link, published_at indexed)             [storage.py]
   ▼
local distilRoBERTa sentiment scoring (offline, no LLM)          [sentiment.py]
   ▼
Streamlit dashboard  +  scheduled email reports                  [dashboard/, watcher.py]
```

## Signal taxonomy (the prompt library)

Every prompt is **anchored on the target company** (queries lead with the company; intents strictly exclude anything not about it) and the Discover call adds `filter_keywords=[company]`, so results stay on-entity rather than pulling in unrelated events. The 7 categories (`src/phantom_bridge/prompts/`):

| Category | Covers |
|----------|--------|
| **financial_performance** | earnings & results, guidance & profit warnings, revenue/demand trends |
| **corporate_actions** | M&A & divestitures, capital/dividends/buybacks, restructuring & layoffs |
| **leadership_governance** | executive & board changes, insider/activist & governance |
| **legal_regulatory** | lawsuits, regulatory actions & fines, approvals & compliance |
| **operations_supply_chain** | facility disruptions, logistics/ports, labor/strikes, accidents & outages |
| **products_partnerships** | launches & recalls, contracts & partnerships, expansion & investment |
| **market_reputation** | analyst ratings, stock moves & sentiment, ESG & controversy |

Each is a JSON list of `{signal, query, intent}` objects — add, remove, or edit a file to reshape coverage.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dashboard]'          # core + sentiment/UI deps
echo "BRIGHT_DATA_API_KEY=your-key" > .env

# Scrape + score + persist one company from the CLI
phantom-bridge "ARAMCO" --results 5    # flags: --country, --db, --no-store

# Or launch the dashboard (Analyze / Watchlist / Settings tabs)
phantom-bridge-dashboard               # → http://localhost:8501

# Background watcher: scrape+score the watchlist on an interval and email a report
phantom-bridge-watch                   # --once for a single cycle (cron-friendly)
```

### Docker

```bash
cp .env.example .env                   # set BRIGHT_DATA_API_KEY
docker compose up --build              # dashboard :8501 + watcher
```

The API key is injected at runtime as an env var — never baked into the image or committed. See [`docs/DEPLOY.md`](docs/DEPLOY.md) for single-container, volumes, and hosting notes, and [`docs/STRUCTURE.md`](docs/STRUCTURE.md) for the code layout.

### Scheduled email reports (the watcher daemon)

`phantom-bridge-watch` is a standalone daemon that periodically scrapes + scores every company on the watchlist and emails one combined report. It reads its config from the same SQLite DB the dashboard writes, so set it up in the UI first:

1. **Settings tab** — fill in the **Bright Data API key** (or rely on `.env`), **SMTP** host/port/username/password (e.g. `smtp.gmail.com` / `587` with a Gmail *app password*), the **From** and **recipient** email, and the **watch interval (hours)**. Save.
2. **Watchlist tab** — add the companies to monitor.
3. **Run it** (in its own terminal, or the compose `watcher` service):
   ```bash
   phantom-bridge-watch           # runs one cycle now, then repeats every N hours
   phantom-bridge-watch --once    # single cycle then exit — for cron / Task Scheduler / systemd
   ```

Each cycle: for every watchlisted company it scrapes fresh news, scores anything new, and (if SMTP + a recipient are set) emails an HTML report — a per-company summary plus the top events with clickable links. Stop the loop with `Ctrl-C` (or stop the container). Restart it to pick up a changed interval. With no SMTP/recipient configured it still scrapes and scores, just logs that the report wasn't sent. You can also trigger one cycle from the dashboard's **Watchlist** tab via **▶ Run watchlist now**.

## Sentiment scoring

[`mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis`](https://huggingface.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis) — DistilRoBERTa fine-tuned on the Financial PhraseBank (Apache-2.0, ~82M params). Runs locally via `transformers` + `torch`, fully offline, no per-call cost. Per item we store: `sentiment_label` (pos/neg/neutral), `sentiment` = P(pos) − P(neg) ∈ [−1, +1], and `confidence`. A finance-tuned model is used deliberately: general-purpose lexicons mis-score financial text (Loughran & McDonald — words like *liability*, *cost*, *risk* are neutral in finance).

**Two honest limitations:**
- **Tone ≠ trade direction.** The model scores the *polarity of the text*, not the price impact. A "refinery fire" reads strongly negative even though a supply cut can be bullish for competitors. The dashboard presents *news sentiment*, not a trade signal — mapping tone to a directional/price signal is the reserved next phase.
- **Document-level, not entity-level.** Without an LLM the score is about the article, not strictly "sentiment toward this company." Anchoring scraping on the company keeps most text on-entity, but mixed-entity articles can still mislead.

## Data model

SQLite (`data/phantom_bridge.db`, gitignored). Raw scraped data is never mutated; derived scores live separately so models can be re-run and compared.

| Table | Purpose |
|-------|---------|
| `events` | raw scraped results — dedup on `UNIQUE(company, link)`, `published_at` indexed |
| `enrichment` | per-event sentiment scores (FK → `events.id`); `financial_score`/`predicted_direction` reserved for the price phase |
| `companies` | ticker / exchange display metadata |
| `settings` | API key, SMTP config, interval (key/value) |
| `watchlist` | companies the watcher monitors |

## Security note

This is a single-user POC. The Bright Data key and SMTP credentials are stored in plaintext (`.env` and the SQLite `settings` table — both gitignored). For the dockerized demo the key is injected as a runtime env var, so it never enters git or the image. Harden (secret manager / encrypted store) before any multi-user or shared deployment.
