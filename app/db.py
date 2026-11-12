"""SQLite storage. One file: ~/WealthPortalData/wealth.db (see WEALTH_DATA_DIR)"""
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    provider      TEXT NOT NULL,            -- 'plaid' | 'manual'
    access_token  TEXT,
    cursor        TEXT,
    products      TEXT,                     -- comma list, e.g. 'transactions,investments'
    is_demo       INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'ok',
    last_synced   TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id                TEXT PRIMARY KEY,
    institution_id    TEXT NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    official_name     TEXT,
    mask              TEXT,
    type              TEXT,      -- depository | credit | investment | loan | other
    subtype           TEXT,      -- checking | savings | credit card | brokerage | hsa ...
    current_balance   REAL DEFAULT 0,
    available_balance REAL,
    credit_limit      REAL,
    currency          TEXT DEFAULT 'USD',
    is_asset          INTEGER DEFAULT 1,  -- 0 for credit cards / loans
    hidden            INTEGER DEFAULT 0,
    updated_at        TEXT
);

-- amount sign convention: money IN is positive, money OUT is negative
-- kind: 'income' | 'spending' | 'transfer'
CREATE TABLE IF NOT EXISTS transactions (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date            TEXT NOT NULL,
    name            TEXT,
    merchant        TEXT,
    amount          REAL NOT NULL,
    category        TEXT,
    category_detail TEXT,
    kind            TEXT NOT NULL,
    pending         INTEGER DEFAULT 0,
    source          TEXT DEFAULT 'plaid',  -- plaid | csv | manual | demo
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);

CREATE TABLE IF NOT EXISTS balance_history (
    date       TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    balance    REAL NOT NULL,
    PRIMARY KEY (date, account_id)
);

CREATE TABLE IF NOT EXISTS holdings (
    account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    security    TEXT,
    ticker      TEXT,
    quantity    REAL,
    value       REAL,
    cost_basis  REAL,
    updated_at  TEXT
);

-- metric: 'net_worth' (everything) | 'accounts' (sum of chosen accounts' balances)
CREATE TABLE IF NOT EXISTS goals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    target_amount REAL NOT NULL,
    target_date   TEXT,
    metric        TEXT NOT NULL DEFAULT 'net_worth',
    account_ids   TEXT,          -- JSON list when metric = 'accounts'
    is_demo       INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT (datetime('now'))
);

-- your own overrides: any transaction whose name/merchant contains pattern gets this category/kind
CREATE TABLE IF NOT EXISTS category_rules (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern   TEXT NOT NULL,
    category  TEXT,
    kind      TEXT
);

CREATE TABLE IF NOT EXISTS statement_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT NOT NULL,
    stored_path  TEXT NOT NULL,
    institution  TEXT,
    period       TEXT,
    pages        INTEGER,
    uploaded_at  TEXT DEFAULT (datetime('now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS statement_pages USING fts5(
    content, statement_id UNINDEXED, page UNINDEXED
);
"""


def connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
    try:
        DB_PATH.chmod(0o600)  # only your user can read the file
    except OSError:
        pass


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
