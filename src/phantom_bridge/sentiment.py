"""Local financial-news sentiment scoring with distilRoBERTa.

Uses ``mrm8488/distilroberta-finetuned-financial-news-sentiment`` (3-class:
positive / negative / neutral) entirely offline — no LLM, no external API.

Per item we derive:
  * ``sentiment``        — continuous, P(positive) - P(negative) in [-1, +1]
  * ``sentiment_label``  — the arg-max class
  * ``confidence``       — the max class probability
"""

import functools

MODEL_NAME = "mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis"
MODEL_VERSION = "distilroberta-financial-v1"
_MAX_LENGTH = 512  # the model's hard token limit


@functools.lru_cache(maxsize=1)
def _pipeline():
    """Load the HF pipeline once per process (lazy — import only when used)."""
    from transformers import pipeline

    return pipeline("text-classification", model=MODEL_NAME, top_k=None)


def event_text(title: str | None, description: str | None) -> str:
    """The text we score for an event: headline + SERP snippet."""
    return " — ".join(p for p in (title, description) if p).strip()


def score_text(text: str | None) -> dict | None:
    """Score one piece of text. Returns None for empty input."""
    text = (text or "").strip()
    if not text:
        return None

    out = _pipeline()(text, truncation=True, max_length=_MAX_LENGTH)
    # text-classification with top_k=None returns list[dict]; batched -> list[list[dict]].
    if out and isinstance(out[0], list):
        out = out[0]

    probs = {d["label"].lower(): d["score"] for d in out}
    top = max(out, key=lambda d: d["score"])
    return {
        "sentiment": round(probs.get("positive", 0.0) - probs.get("negative", 0.0), 6),
        "sentiment_label": top["label"].lower(),
        "confidence": round(top["score"], 6),
    }
