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

# App Service sets WEBSITE_SITE_NAME on every web app, so its presence means "running in Azure".
ON_AZURE = bool(os.getenv("WEBSITE_SITE_NAME"))

# Where your database + uploaded statements live. Keep this OUT of OneDrive/iCloud/Dropbox.
# On App Service only /home survives restarts and redeploys, so the default moves there.
_DEFAULT_DATA_DIR = "/home/data" if ON_AZURE else "~/WealthPortalData"
DATA_DIR = Path(os.getenv("WEALTH_DATA_DIR", _DEFAULT_DATA_DIR)).expanduser()
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

# Encrypts Plaid access tokens in the database (see app/crypto.py). Required on Azure (from Key Vault);
# on your own computer a key file is created in DATA_DIR if this is empty.
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")

# Sign-in check (see app/security.py). On App Service, Entra ID sign-in happens before a request
# reaches the app; the app then refuses anyone not listed here, as a second lock.
# ALLOWED_USERS: comma-separated Entra ID object IDs (preferred: not guessable) and/or sign-in emails.
REQUIRE_SIGN_IN = os.getenv("REQUIRE_SIGN_IN", "true" if ON_AZURE else "false").lower() == "true"
ALLOWED_USERS = {u.strip().lower() for u in os.getenv("ALLOWED_USERS", "").split(",") if u.strip()}

# Locally: listen on 127.0.0.1 so only your computer can reach the portal.
# On App Service: listen on 0.0.0.0; App Service's front end (with Entra ID sign-in) is the only way in.
HOST = os.getenv("HOST", "0.0.0.0" if ON_AZURE else "127.0.0.1")
PORT = int(os.getenv("PORT") or os.getenv("WEBSITES_PORT") or ("8000" if ON_AZURE else "8765"))
