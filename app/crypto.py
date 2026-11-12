"""Encrypts Plaid access tokens before they are written to the database.

Why: a Plaid access token is a live key to read a bank account. If someone got a copy of the
database file (a backup, a stray download), plaintext tokens would let them pull your
transactions. Encrypted, the file is useless without the key, which lives somewhere else:
Azure Key Vault in production, a separate key file on your own computer.

How: Fernet (AES-128 in CBC mode with an HMAC-SHA256 signature, from the `cryptography`
package). Encrypted values are stored as "enc:v1:<token>" so the code can tell them apart
from older plaintext values and upgrade those in place.

Key: TOKEN_ENCRYPTION_KEY, a Fernet key. Generate one with
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
If you lose the key, stored tokens can't be decrypted and each bank must be connected again.
"""
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from . import config

PREFIX = "enc:v1:"
LOCAL_KEY_FILE = config.DATA_DIR / "token.key"


class MissingKeyError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = config.TOKEN_ENCRYPTION_KEY
    if not key:
        if config.ON_AZURE:
            # In production the key must come from Key Vault; never invent one on the server,
            # or a redeploy that loses it would silently lock every bank connection.
            raise MissingKeyError("TOKEN_ENCRYPTION_KEY is not set. Add it to Key Vault and the app settings.")
        # On your own computer: create a key file once, readable only by you.
        if not LOCAL_KEY_FILE.exists():
            LOCAL_KEY_FILE.write_bytes(Fernet.generate_key())
            os.chmod(LOCAL_KEY_FILE, 0o600)
        key = LOCAL_KEY_FILE.read_text().strip()
    return Fernet(key.encode() if isinstance(key, str) else key)


def ensure_key() -> None:
    """Raise MissingKeyError now, before work that would leave a token with nowhere safe to go."""
    _fernet()


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(plain: str | None) -> str | None:
    if not plain or is_encrypted(plain):
        return plain
    return PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt(stored: str | None) -> str | None:
    if not is_encrypted(stored):
        return stored  # older plaintext value (upgraded at startup) or empty
    try:
        return _fernet().decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("A stored Plaid token can't be decrypted: TOKEN_ENCRYPTION_KEY changed. "
                           "Restore the old key, or disconnect and reconnect the bank.") from e


def encrypt_plaintext_tokens(conn) -> int:
    """Upgrade any plaintext tokens left from before encryption existed. Returns how many."""
    rows = conn.execute("SELECT id, access_token FROM institutions "
                        "WHERE access_token IS NOT NULL AND access_token != '' "
                        "AND access_token NOT LIKE ?", (PREFIX + "%",)).fetchall()
    for r in rows:
        conn.execute("UPDATE institutions SET access_token=? WHERE id=?", (encrypt(r["access_token"]), r["id"]))
    return len(rows)
