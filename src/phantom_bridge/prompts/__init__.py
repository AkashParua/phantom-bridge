"""Prompt library: one JSON file per disruption category.

Each file is a list of ``{signal, query, intent}`` objects. ``load_prompts``
flattens them into a single list, tagging each with its source file's stem as
``category``.
"""

import json
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


def load_prompts() -> list[dict]:
    """Read every *.json prompt file and flatten into one list of signals."""
    prompts: list[dict] = []
    for path in sorted(PROMPT_DIR.glob("*.json")):
        for item in json.loads(path.read_text()):
            prompts.append({"category": path.stem, **item})
    return prompts
