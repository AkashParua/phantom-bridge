# phantom-bridge demo image — Streamlit sentiment dashboard.
#
# Build:  docker build -t phantom-bridge .
# Run:    docker run -p 8501:8501 -e BRIGHT_DATA_API_KEY=your-key phantom-bridge
#
# The API key is injected at runtime as an env var — it is NEVER baked into the
# image or copied from .env (see .dockerignore). The app reads it via
# config.get_api_key(); the dashboard Settings tab can still override it.

FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.hf-cache \
    TRANSFORMERS_NO_ADVISORY_WARNINGS=1

WORKDIR /app

# CPU-only PyTorch first — avoids pulling the large CUDA build into the image.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

# Install the package with dashboard extras (editable keeps DEFAULT_DB at /app/data).
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e '.[dashboard]'

# Pre-download the sentiment model so the first request is fast and the
# container doesn't depend on Hugging Face being reachable at run time.
RUN python -c "from transformers import pipeline; \
    pipeline('text-classification', \
    model='mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis')"

EXPOSE 8501

# Honors $PORT if the host sets one; defaults to 8501.
CMD ["sh", "-c", "streamlit run src/phantom_bridge/dashboard/app.py \
    --server.address=0.0.0.0 --server.port=${PORT:-8501} --server.headless=true"]
