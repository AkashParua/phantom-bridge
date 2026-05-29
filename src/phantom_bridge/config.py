"""Runtime configuration: filesystem paths and credentials."""

import os
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]  # src/phantom_bridge -> src -> repo root
DEFAULT_DB = PROJECT_ROOT / "data" / "phantom_bridge.db"


def get_api_key() -> str | None:
    """Load .env (if present) and return the Bright Data API key, or None."""
    load_dotenv()
    return os.environ.get("BRIGHT_DATA_API_KEY")
