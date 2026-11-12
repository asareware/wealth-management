"""Settings, loaded from a .env file next to the project (no extra dependency)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")

# Where your database + uploaded statements live. Keep this OUT of OneDrive/iCloud/Dropbox.
DATA_DIR = Path(os.getenv("WEALTH_DATA_DIR", "~/WealthPortalData")).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATEMENTS_DIR = DATA_DIR / "statements"
STATEMENTS_DIR.mkdir(exist_ok=True)

DB_PATH = Path(os.getenv("WEALTH_DB", DATA_DIR / "wealth.db"))

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")
PLAID_ENV = os.getenv("PLAID_ENV", "production").lower()  # "production" or "sandbox"
PLAID_REDIRECT_URI = os.getenv("PLAID_REDIRECT_URI", "")  # optional; not needed on desktop web

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-5-5")

HOST = os.getenv("HOST", "127.0.0.1")  # keep it on your machine only
PORT = int(os.getenv("PORT", "8765"))
