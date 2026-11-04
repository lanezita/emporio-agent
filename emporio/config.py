"""Settings. Everything the rest of the code needs to know about the environment."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNTIME_DIR = ROOT / "runtime"  # chat sessions and hand-off tickets (git-ignored)

load_dotenv(ROOT / ".env")

# The model can be changed without touching the code: GEMINI_MODEL=... in .env
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Campo Grande/MS. The store hours in the manual are in this time zone.
STORE_TZ = ZoneInfo("America/Campo_Grande")


def now() -> datetime:
    """Current time in the store's time zone.

    Set EMPORIO_NOW (ISO format, e.g. 2026-11-03T10:30) to freeze the clock.
    This makes demos and tests repeatable.
    """
    fixed = os.getenv("EMPORIO_NOW")
    if fixed:
        return datetime.fromisoformat(fixed).replace(tzinfo=STORE_TZ)
    return datetime.now(STORE_TZ)
