"""Test setup: every test run gets its own empty data folder and encryption key,
so tests never touch your real database."""
import os
import tempfile

from cryptography.fernet import Fernet

# Must be set before the app is imported: app/config.py reads these once at import time.
os.environ["WEALTH_DATA_DIR"] = tempfile.mkdtemp(prefix="wealth-test-")
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("WEBSITE_SITE_NAME", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PORTAL_HEADERS = {"X-Wealth-Portal": "1"}


@pytest.fixture
def client():
    with TestClient(app) as c:  # "with" runs the app's startup (creates the database)
        yield c
