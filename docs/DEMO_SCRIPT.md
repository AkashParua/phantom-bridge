# phantom-bridge — Video Demo Script

A follow-along script for recording the demo. Two parts: a **one-time pre-flight**
(do this before you hit record) and the **scene-by-scene script** (what to do +
what to say). Target length: ~3–4 minutes.

---

## Part 0 — Pre-flight (BEFORE recording)

> The only thing that can fail live is the email (SMTP). Test it once first.

- [ ] **Dashboard is running** → http://localhost:8501 (WSL fallback: the Network URL).
- [ ] **API key set** — `.env` has `BRIGHT_DATA_API_KEY`, or set it in the Settings tab.
- [ ] **Configure email** (Settings tab):
  - SMTP host: `smtp.gmail.com`  ·  port: `587`
  - SMTP username: your Gmail address
  - SMTP password: a **Gmail App Password** (Google Account → Security → 2-Step
    Verification → App passwords). *The normal Gmail password will NOT work.*
  - From email: your Gmail  ·  Recipient: where the report should land
  - **Results per query (watcher): 3**  ← keeps the demo scrape fast
  - Click **Save settings**
- [ ] **Watchlist tab** → add ONE company (e.g. `Nvidia`).
- [ ] **Dry-run the email** → click **▶ Run watchlist now** → wait for
      "Cycle complete" → **confirm the email arrived in your inbox.**
      (If it works once, it'll work on camera.)
- [ ] **Pre-warm the app demo** → on Analyze, run `ARAMCO` (instant, already cached)
      and any fresh company you'll show, so there's no waiting during recording.
- [ ] Set the **Analyze "Results per query" slider to 3** as well.

---

## Part 1 — The Script

### Scene 1 · The pitch  (~15s)
**DO:** Have the README (or the dashboard) on screen.
**SAY:**
> "phantom-bridge turns the open web's scattered, real-time news about a public
> company into a clean, sentiment-scored signal feed. You type a company name; it
> pulls fresh coverage across seven dimensions, scores each story's financial
> sentiment with a local model, and shows it in a dashboard — plus scheduled
> email digests. The stack is Bright Data Discover for retrieval, a distilRoBERTa
> model for sentiment, SQLite for storage, and Streamlit for the UI."

### Scene 2 · Analyze a company  (~60s)
**DO:** Analyze tab → type the company → point at the **Results per query** slider →
click **Analyze**.
**SAY (while it loads):**
> "Under the hood, 21 company-anchored prompts fan out across 7 categories —
> financials, legal and regulatory, leadership, operations and supply chain,
> deals, products, and reputation. Every query leads with the company and results
> are keyword-filtered to it, so unrelated events don't leak in."

**DO (when results render):** point at the metrics → the sentiment timeline →
sort the table by sentiment → click an **"open ↗"** link (proves it's real news) →
toggle **Filter by publish date**.
**SAY:**
> "Here's the aggregate sentiment, the trend over time, and every scored story.
> Negative stories float to the top — I can click straight through to the source."

### Scene 3 · How scoring works  (~20s)
**SAY:**
> "Each headline is scored by a distilRoBERTa model fine-tuned on financial news,
> running fully offline — no LLM, no API cost, nothing leaves the machine. The raw
> scrape is never mutated; scores live in a separate table so models can be re-run
> and compared."

### Scene 4 · Watchlist + the email  (~60s)
**DO:** Watchlist tab → show the watchlisted company → click
**▶ Run watchlist now**.
**SAY:**
> "The same pipeline runs unattended. A background daemon — phantom-bridge-watch —
> scrapes, scores, and emails a digest on a schedule. Let me trigger one cycle now."

**DO:** Cut to your **inbox** → open the report email.
**SAY:**
> "Here's the report: a per-company summary — how many stories, average sentiment,
> the negative/positive split — and the top events as clickable links. This lands
> in my inbox every interval, completely hands-off."

### Scene 5 · Config & deploy, wrap  (~15s)
**DO:** Settings tab (show API key / SMTP / interval fields).
**SAY:**
> "Everything's configured in-app, and secrets stay local. The whole thing is
> dockerized — `docker compose up` brings up the dashboard and the watcher
> together. That's phantom-bridge."

---

## Recording tips

- **Set both result sliders to 3** while recording — fewer items, faster scrapes.
- **Avoid dead air:** a *fresh* company scrape takes a couple of minutes. Pre-warm
  it and re-Analyze (instant from cache), narrate the architecture while it runs,
  or cut the wait in editing.
- **Email:** trigger the watchlist run, then **cut** to the already-arrived inbox —
  don't film the wait.
- **Hero shots:** the metrics row + sentiment timeline make a clean visual.
- If the UI errors, the log is at `/tmp/pb_dash.log`.

## One-liner (for the submission blurb)

> phantom-bridge turns the web's real-time news about any public company into a
> clean, sentiment-scored signal feed — with a live dashboard and scheduled email
> digests.
