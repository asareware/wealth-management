"""Bank PDF statements (upload + full-text search) and CSV transaction import."""
import csv
import datetime as dt
import hashlib
import io
import re
import shutil
from pathlib import Path

from pypdf import PdfReader

from .categorize import apply_rules, classify
from .config import STATEMENTS_DIR
from .db import rows


# ---------- PDF statements ----------

def index_pdf(conn, src: Path, original_name: str, institution: str = "", period: str = "") -> dict:
    digest = hashlib.sha1(src.read_bytes()).hexdigest()[:10]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name)
    dest = STATEMENTS_DIR / f"{digest}_{safe}"
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    reader = PdfReader(str(dest))
    cur = conn.execute("INSERT INTO statement_files (filename, stored_path, institution, period, pages) "
                       "VALUES (?,?,?,?,?)", (original_name, str(dest), institution, period, len(reader.pages)))
    sid = cur.lastrowid
    empty = 0
    for n, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if not text.strip():
            empty += 1
        conn.execute("INSERT INTO statement_pages (content, statement_id, page) VALUES (?,?,?)", (text, sid, n))
    return {"id": sid, "pages": len(reader.pages), "pages_without_text": empty}


def list_statements(conn) -> list[dict]:
    return rows(conn, "SELECT id, filename, institution, period, pages, uploaded_at FROM statement_files "
                      "ORDER BY uploaded_at DESC")


def search_statements(conn, query: str, limit: int = 20) -> list[dict]:
    terms = [w for w in re.findall(r"[A-Za-z0-9$.]+", query) if w]
    if not terms:
        return []
    fts = " ".join(f'"{w}"' for w in terms)
    return rows(conn, """SELECT f.id, f.filename, f.institution, f.period, p.page,
               snippet(statement_pages, 0, '<mark>', '</mark>', ' … ', 18) AS snippet
        FROM statement_pages p JOIN statement_files f ON f.id = p.statement_id
        WHERE statement_pages MATCH ? ORDER BY rank LIMIT ?""", (fts, limit))


def delete_statement(conn, sid: int) -> None:
    r = conn.execute("SELECT stored_path FROM statement_files WHERE id=?", (sid,)).fetchone()
    if r:
        Path(r["stored_path"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM statement_pages WHERE statement_id=?", (sid,))
    conn.execute("DELETE FROM statement_files WHERE id=?", (sid,))


# ---------- CSV import (for any account a bank connection can't reach) ----------

DATE_KEYS = ("date", "transaction date", "posting date", "posted date", "trade date")
DESC_KEYS = ("description", "name", "payee", "merchant", "memo", "details")
AMT_KEYS = ("amount", "net amount")
DEBIT_KEYS = ("debit", "withdrawal", "withdrawals")
CREDIT_KEYS = ("credit", "deposit", "deposits")


def _pick(headers, keys):
    low = {h.lower().strip(): h for h in headers}
    for k in keys:
        if k in low:
            return low[k]
    return None


def _money(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(",", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _date(v) -> str | None:
    v = (v or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def import_csv(conn, account_id: str, data: bytes, flip_sign: bool = False) -> dict:
    """Generic bank CSV. Money in should be positive; tick flip_sign if your bank exports the opposite."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    h = reader.fieldnames or []
    dk, sk, ak = _pick(h, DATE_KEYS), _pick(h, DESC_KEYS), _pick(h, AMT_KEYS)
    deb, cre = _pick(h, DEBIT_KEYS), _pick(h, CREDIT_KEYS)
    catk = _pick(h, ("category",))
    if not dk or not sk or not (ak or deb or cre):
        return {"ok": False, "error": f"Couldn't find date/description/amount columns in: {h}"}
    added = skipped = 0
    for r in reader:
        d = _date(r.get(dk))
        if ak:
            amt = _money(r.get(ak))
        else:
            amt = (_money(r.get(cre)) or 0) - abs(_money(r.get(deb)) or 0)
        if d is None or amt is None:
            skipped += 1
            continue
        if flip_sign:
            amt = -amt
        desc = (r.get(sk) or "").strip()
        tid = "csv_" + hashlib.sha1(f"{account_id}|{d}|{desc}|{amt}".encode()).hexdigest()[:20]
        kind, cat = classify(amt, None, desc)
        if catk and r.get(catk):
            cat = r[catk].strip()
        tx = apply_rules(conn, {"id": tid, "account_id": account_id, "date": d, "name": desc,
                                "merchant": None, "amount": amt, "category": cat, "kind": kind})
        cur = conn.execute("""INSERT OR IGNORE INTO transactions (id, account_id, date, name, merchant, amount,
                   category, kind, source) VALUES (:id,:account_id,:date,:name,:merchant,:amount,:category,:kind,'csv')""",
                           tx)
        added += cur.rowcount
        skipped += 1 - cur.rowcount
    return {"ok": True, "added": added, "skipped_or_duplicate": skipped}
