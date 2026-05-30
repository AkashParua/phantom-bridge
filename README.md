# phantom-bridge

> **Real-time company intelligence — read a company's signals before the market does.**

**phantom-bridge** turns the open web's scattered, real-time news about a public company into a clean, sentiment-scored signal feed. Type a company name; it pulls fresh coverage across seven dimensions — financials, legal/regulatory, leadership, operations & supply chain, deals, products, and reputation — ties every story back to that company, scores each one's financial sentiment with a **local** model, and surfaces it in a live dashboard with scheduled email digests for your watchlist.

`Python` · `Streamlit` · `Bright Data Discover` · `distilRoBERTa` · `SQLite` · `Docker`

## What it does

- 🔎 **One input, holistic coverage** — a company-anchored prompt library fans out across 7 news categories so you see the whole picture, not just one beat.
- 🎯 **On-entity, not noise** — queries lead with the company and results are keyword-filtered to it, so unrelated events don't leak in.
- 🧠 **Finance-tuned sentiment, fully local** — every story scored by a distilRoBERTa model running offline (no LLM, no API cost, no data leaving the box).
- 📊 **Live dashboard** — analyze any company on demand, manage a watchlist, and configure everything in-app.
- 📬 **Scheduled email digests** — a background daemon scrapes, scores, and emails a per-company report on your chosen interval.
- 🐳 **One-command demo** — `docker compose up` brings up the dashboard and the watcher together.

## Why it matters

In finance, the edge — *alpha* — goes to whoever understands a company first. But the official record (earnings, filings, structured feeds) is **retrospective**: it confirms what already happened, often a quarter late. A company's real story plays out first across thousands of news sites, regulators, and press releases — fast, unstructured, and easy to miss.

phantom-bridge continuously reads that live stream, resolves every item to the target company, scores its sentiment, and structures it into a clean, queryable, time-stamped record — so a shift in a company's narrative is visible **as it forms**, not after the fact.

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
3. **Run it** (own terminal, or the compose `watcher` service):
   ```bash
   phantom-bridge-watch           # runs one cycle now, then repeats every N hours
   phantom-bridge-watch --once    # single cycle then exit — for cron / Task Scheduler / systemd
   ```

Each cycle scrapes fresh news per company, scores anything new, and (if SMTP + a recipient are set) emails an HTML report — a per-company summary plus top events with clickable links. Stop with `Ctrl-C`; restart to pick up a changed interval. You can also trigger one cycle from the dashboard's **Watchlist** tab via **▶ Run watchlist now**.

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
