"""Plan step 2: the security checks."""
import pytest

from app import ai, config, crypto
from app.db import session

from .conftest import PORTAL_HEADERS

FAKE_TOKEN = "access-production-11111111-2222-3333-4444-555555555555"


@pytest.fixture
def bank_with_token(client):
    with session() as conn:
        conn.execute("INSERT OR REPLACE INTO institutions (id, name, provider, access_token, cursor) "
                     "VALUES ('test_bank', 'Test Bank', 'plaid', ?, 'cursor-abc')", (crypto.encrypt(FAKE_TOKEN),))
    yield "test_bank"
    with session() as conn:
        conn.execute("DELETE FROM institutions WHERE id='test_bank'")


# ---------- 1. the AI can't read Plaid tokens ----------

def test_ai_select_star_hides_token_columns(bank_with_token):
    out = ai._run_sql("SELECT * FROM institutions WHERE id='test_bank'")
    row = out["rows"][0]
    assert row["name"] == "Test Bank"          # normal columns still work
    assert row["access_token"] is None         # secret columns come back empty
    assert row["cursor"] is None


@pytest.mark.parametrize("sql", [
    "SELECT access_token FROM institutions",
    "SELECT ACCESS_TOKEN AS x FROM INSTITUTIONS",
    "WITH t AS (SELECT access_token AS a FROM institutions) SELECT a FROM t",
    "SELECT (SELECT access_token FROM institutions LIMIT 1) AS sneaky",
])
def test_ai_cannot_reach_token_any_way(bank_with_token, sql):
    out = ai._run_sql(sql)
    assert FAKE_TOKEN not in str(out)
    assert crypto.PREFIX not in str(out)


def test_ai_still_blocks_writes():
    assert "error" in ai._run_sql("DELETE FROM institutions")


# ---------- 2. tokens are encrypted at rest ----------

def test_token_is_stored_encrypted(bank_with_token):
    with session() as conn:
        stored = conn.execute("SELECT access_token FROM institutions WHERE id='test_bank'").fetchone()[0]
    assert stored.startswith(crypto.PREFIX) and FAKE_TOKEN not in stored
    assert crypto.decrypt(stored) == FAKE_TOKEN


def test_old_plaintext_tokens_are_upgraded(client):
    with session() as conn:
        conn.execute("INSERT INTO institutions (id, name, provider, access_token) "
                     "VALUES ('old_bank', 'Old Bank', 'plaid', ?)", (FAKE_TOKEN,))
        assert crypto.encrypt_plaintext_tokens(conn) == 1
        stored = conn.execute("SELECT access_token FROM institutions WHERE id='old_bank'").fetchone()[0]
        conn.execute("DELETE FROM institutions WHERE id='old_bank'")
    assert crypto.is_encrypted(stored) and crypto.decrypt(stored) == FAKE_TOKEN


# ---------- 3. sign-in allow-list ----------

OWNER_ID = "00000000-aaaa-bbbb-cccc-000000000001"


@pytest.fixture
def signed_in_mode(monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_SIGN_IN", True)
    monkeypatch.setattr(config, "ALLOWED_USERS", {OWNER_ID})


def test_no_sign_in_is_refused(client, signed_in_mode):
    assert client.get("/api/status").status_code == 401
    assert client.get("/").status_code == 401


def test_other_user_is_refused(client, signed_in_mode):
    headers = {"X-MS-CLIENT-PRINCIPAL-ID": "99999999-0000-0000-0000-000000000000",
               "X-MS-CLIENT-PRINCIPAL-NAME": "someone@else.com"}
    assert client.get("/api/status", headers=headers).status_code == 403


def test_owner_gets_in(client, signed_in_mode):
    headers = {"X-MS-CLIENT-PRINCIPAL-ID": OWNER_ID, "X-MS-CLIENT-PRINCIPAL-NAME": "owner@example.com"}
    r = client.get("/api/status", headers=headers)
    assert r.status_code == 200 and r.json()["user"] == "owner@example.com"


def test_empty_allow_list_lets_nobody_in(client, monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_SIGN_IN", True)
    monkeypatch.setattr(config, "ALLOWED_USERS", set())
    headers = {"X-MS-CLIENT-PRINCIPAL-ID": OWNER_ID}
    assert client.get("/api/status", headers=headers).status_code == 403


def test_health_check_needs_no_sign_in(client, signed_in_mode):
    assert client.get("/healthz").json() == {"ok": True}


# ---------- 4. CSRF header on writes ----------

def test_write_without_portal_header_is_blocked(client):
    r = client.post("/api/rules", json={"pattern": "X", "category": "Y"})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]


def test_write_with_portal_header_works(client):
    r = client.post("/api/rules", json={"pattern": "TEST-RULE", "category": "Test"}, headers=PORTAL_HEADERS)
    assert r.status_code == 200


def test_reads_need_no_header(client):
    assert client.get("/api/rules").status_code == 200
