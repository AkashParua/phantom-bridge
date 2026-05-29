# Deploying the phantom-bridge demo

The app runs as a Docker container. The **Bright Data API key is injected at
runtime as an environment variable** (`BRIGHT_DATA_API_KEY`) — it is never baked
into the image or committed (see `.dockerignore`). The app reads it via
`config.get_api_key()`; the dashboard **Settings** tab can also override it.

## 1. Single container (dashboard only)

```bash
docker build -t phantom-bridge .
docker run -p 8501:8501 -e BRIGHT_DATA_API_KEY=your-key phantom-bridge
# open http://localhost:8501
```

Persist the SQLite DB across restarts by mounting a volume (the DB lives at
`/app/data/phantom_bridge.db`):

```bash
docker run -p 8501:8501 -e BRIGHT_DATA_API_KEY=your-key \
  -v "$(pwd)/data:/app/data" phantom-bridge
```

## 2. Full demo with Docker Compose (dashboard + watcher)

```bash
cp .env.example .env          # then edit .env and set BRIGHT_DATA_API_KEY
docker compose up --build
```

- **dashboard** → http://localhost:8501
- **watcher** → background daemon (`phantom-bridge-watch`) that, on the configured
  interval, scrapes + scores the watchlist and emails a report.

Both services share the `./data` volume, so the watcher reads the watchlist and
SMTP settings you save in the dashboard. Configure SMTP + the recipient email +
the watchlist in the dashboard's **Watchlist** and **Settings** tabs first; until
then the watcher just logs "watchlist is empty" and sleeps.

Run a single watcher cycle (e.g. for cron) instead of the loop:

```bash
docker compose run --rm watcher phantom-bridge-watch --once
```

## Secrets

- **Local dev:** `.env` (gitignored). Copy from `.env.example`.
- **Docker:** pass `-e BRIGHT_DATA_API_KEY=...`, or use `env_file: .env` (compose).
  Never `COPY .env` into the image.
- **Hosted:** put the key in the platform's Secrets/Env UI so it arrives as an
  env var. The key never touches git or the image layers.

## Resource requirements

- **~1.5–2 GB RAM** (PyTorch + the distilRoBERTa model). Free 512 MB tiers cannot
  import torch — pick an instance with ≥2 GB.
- The image pre-downloads the sentiment model at build time (~330 MB), so the
  first request is fast and runtime doesn't depend on Hugging Face being reachable.

## Hosting notes

This same image runs on any container host. The `CMD` honors `$PORT` if the
platform sets one (defaults to 8501).

- **Hugging Face Spaces (Docker SDK)** — recommended free option: 16 GB RAM,
  built-in Secrets manager for `BRIGHT_DATA_API_KEY`, ML-friendly. Sets `$PORT`
  (7860), which the CMD already handles.
- **Railway / Render (paid) / a VM** — set the env var in the platform's settings;
  attach a volume/disk at `/app/data` if you want the DB to persist.

> Note: SQLite is single-writer. The dashboard and watcher sharing one DB file is
> fine for a demo (WAL mode + short writes), but it is not built for heavy
> concurrent write load.
