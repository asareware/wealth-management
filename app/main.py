"""Wealth Portal web server. Run:  python run.py   then open http://127.0.0.1:8765"""
import csv
import datetime as dt
import io
import json
import tempfile
import threading
import time
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import ai, config, demo, db, files, metrics, plaid_sync
from .db import rows, session

app = FastAPI(title="Wealth Portal")
STATIC = config.ROOT / "static"


@app.on_event("startup")
def _startup():
    db.init()
    if plaid_sync.configured():
        def loop():
            while True:
                try:
                    plaid_sync.sync_all()
                except Exception as e:  # noqa: BLE001
                    print("Background sync failed:", e)
                time.sleep(6 * 3600)
        threading.Thread(target=loop, daemon=True).start()


@app.get("/healthz")
def healthz():
    """Used by App Service's health check: is the app up and can it reach its database?"""
    with session() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------- status / overview ----------

@app.get("/api/status")
def status():
    with session() as conn:
        n_acc = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        demo_on = conn.execute("SELECT COUNT(*) FROM institutions WHERE is_demo=1").fetchone()[0] > 0
    return {"plaid_configured": plaid_sync.configured(), "plaid_env": config.PLAID_ENV,
            "ai_configured": bool(config.ANTHROPIC_API_KEY), "ai_model": config.AI_MODEL,
            "accounts": n_acc, "demo": demo_on, "today": dt.date.today().isoformat()}


@app.get("/api/overview")
def overview(period: str = "month"):
    with session() as conn:
        return metrics.overview(conn, period)


# ---------- institutions & accounts ----------

@app.get("/api/institutions")
def institutions():
    with session() as conn:
        return rows(conn, "SELECT id, name, provider, status, last_synced, is_demo, products FROM institutions ORDER BY name")


@app.delete("/api/institutions/{inst_id}")
def delete_institution(inst_id: str):
    plaid_sync.remove_institution(inst_id)
    return {"ok": True}


@app.get("/api/accounts")
def get_accounts(include_hidden: bool = False):
    with session() as conn:
        accs = rows(conn, """SELECT a.*, i.name AS institution, i.provider, i.status AS institution_status,
                                    i.last_synced, i.is_demo
                             FROM accounts a JOIN institutions i ON i.id=a.institution_id
                             WHERE (? OR a.hidden=0) ORDER BY i.name, a.name""", (int(include_hidden),))
        for a in accs:
            a["holdings"] = rows(conn, "SELECT security, ticker, quantity, value, cost_basis FROM holdings "
                                       "WHERE account_id=? ORDER BY value DESC", (a["id"],)) if a["type"] == "investment" else []
        return accs


@app.patch("/api/accounts/{acc_id}")
def update_account(acc_id: str, body: dict = Body(...)):
    allowed = {k: body[k] for k in ("name", "hidden") if k in body}
    with session() as conn:
        for k, v in allowed.items():
            conn.execute(f"UPDATE accounts SET {k}=? WHERE id=?", (v, acc_id))
    return {"ok": True}


@app.post("/api/manual-accounts")
def add_manual_account(body: dict = Body(...)):
    """For anything you can't connect (e.g. if Webull won't link): enter the balance yourself."""
    inst_name = body.get("institution", "").strip() or "Manual"
    typ = body.get("type", "depository")
    with session() as conn:
        inst = conn.execute("SELECT id FROM institutions WHERE name=? AND provider='manual' AND is_demo=0",
                            (inst_name,)).fetchone()
        inst_id = inst["id"] if inst else "manual_" + plaid_sync.new_id()
        if not inst:
            conn.execute("INSERT INTO institutions (id, name, provider) VALUES (?,?, 'manual')", (inst_id, inst_name))
        acc_id = "manual_" + plaid_sync.new_id()
        bal = float(body.get("balance") or 0)
        conn.execute("""INSERT INTO accounts (id, institution_id, name, type, subtype, current_balance, is_asset, updated_at)
                        VALUES (?,?,?,?,?,?,?,datetime('now'))""",
                     (acc_id, inst_id, body.get("name") or inst_name, typ, body.get("subtype", ""), bal,
                      0 if typ in ("credit", "loan") else 1))
        conn.execute("INSERT OR REPLACE INTO balance_history VALUES (?,?,?)", (dt.date.today().isoformat(), acc_id, bal))
    return {"ok": True, "id": acc_id}


@app.post("/api/accounts/{acc_id}/balance")
def set_balance(acc_id: str, body: dict = Body(...)):
    bal = float(body["balance"])
    day = body.get("date") or dt.date.today().isoformat()
    with session() as conn:
        conn.execute("UPDATE accounts SET current_balance=?, updated_at=datetime('now') WHERE id=?", (bal, acc_id))
        conn.execute("INSERT OR REPLACE INTO balance_history VALUES (?,?,?)", (day, acc_id, bal))
    return {"ok": True}


# ---------- transactions ----------

@app.get("/api/transactions")
def transactions(q: str = "", account: str = "", category: str = "", kind: str = "", start: str = "",
                 end: str = "", min_amount: float | None = None, max_amount: float | None = None,
                 limit: int = 100, offset: int = 0):
    where, params = ["a.hidden=0"], []
    if q:
        where.append("(t.name LIKE ? OR t.merchant LIKE ? OR t.category LIKE ? OR t.notes LIKE ?)")
        params += [f"%{q}%"] * 4
    for col, val in (("t.account_id", account), ("t.category", category), ("t.kind", kind)):
        if val:
            where.append(f"{col}=?"); params.append(val)
    if start:
        where.append("t.date>=?"); params.append(start)
    if end:
        where.append("t.date<=?"); params.append(end)
    if min_amount is not None:
        where.append("ABS(t.amount)>=?"); params.append(min_amount)
    if max_amount is not None:
        where.append("ABS(t.amount)<=?"); params.append(max_amount)
    w = " AND ".join(where)
    base = f"FROM transactions t JOIN accounts a ON a.id=t.account_id JOIN institutions i ON i.id=a.institution_id WHERE {w}"
    with session() as conn:
        agg = conn.execute(f"SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN t.amount>0 THEN t.amount END),0) inflow, "
                           f"COALESCE(SUM(CASE WHEN t.amount<0 THEN t.amount END),0) outflow {base}", params).fetchone()
        data = rows(conn, f"""SELECT t.*, a.name AS account, i.name AS institution {base}
                              ORDER BY t.date DESC, t.id LIMIT ? OFFSET ?""", params + [limit, offset])
    return {"total": agg["n"], "inflow": round(agg["inflow"], 2), "outflow": round(-agg["outflow"], 2), "rows": data}


@app.patch("/api/transactions/{tx_id}")
def update_transaction(tx_id: str, body: dict = Body(...)):
    with session() as conn:
        for k in ("category", "kind", "notes"):
            if k in body:
                conn.execute(f"UPDATE transactions SET {k}=? WHERE id=?", (body[k], tx_id))
    return {"ok": True}


@app.get("/api/categories")
def categories():
    with session() as conn:
        return [r["category"] for r in conn.execute("SELECT DISTINCT category FROM transactions WHERE category IS NOT NULL ORDER BY category")]


@app.get("/api/transactions.csv")
def export_csv(start: str = "", end: str = ""):
    with session() as conn:
        data = rows(conn, """SELECT t.date, i.name AS institution, a.name AS account, COALESCE(t.merchant,t.name) AS description,
                                    t.amount, t.category, t.kind, t.notes
                             FROM transactions t JOIN accounts a ON a.id=t.account_id JOIN institutions i ON i.id=a.institution_id
                             WHERE (?='' OR t.date>=?) AND (?='' OR t.date<=?) ORDER BY t.date""", (start, start, end, end))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(data[0].keys()) if data else ["date"])
    w.writeheader(); w.writerows(data)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=transactions.csv"})


# ---------- category rules ----------

@app.get("/api/rules")
def get_rules():
    with session() as conn:
        return rows(conn, "SELECT * FROM category_rules ORDER BY id")


@app.post("/api/rules")
def add_rule(body: dict = Body(...)):
    pattern = body["pattern"].strip()
    with session() as conn:
        conn.execute("INSERT INTO category_rules (pattern, category, kind) VALUES (?,?,?)",
                     (pattern, body.get("category") or None, body.get("kind") or None))
        if body.get("apply_existing", True):
            like = f"%{pattern}%"
            if body.get("category"):
                conn.execute("UPDATE transactions SET category=? WHERE name LIKE ? OR merchant LIKE ?", (body["category"], like, like))
            if body.get("kind"):
                conn.execute("UPDATE transactions SET kind=? WHERE name LIKE ? OR merchant LIKE ?", (body["kind"], like, like))
    return {"ok": True}


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int):
    with session() as conn:
        conn.execute("DELETE FROM category_rules WHERE id=?", (rule_id,))
    return {"ok": True}


# ---------- goals ----------

@app.get("/api/goals")
def goals():
    with session() as conn:
        return metrics.goal_progress(conn)


@app.post("/api/goals")
def add_goal(body: dict = Body(...)):
    with session() as conn:
        conn.execute("INSERT INTO goals (name, target_amount, target_date, metric, account_ids) VALUES (?,?,?,?,?)",
                     (body["name"], float(body["target_amount"]), body.get("target_date") or None,
                      body.get("metric", "net_worth"), json.dumps(body.get("account_ids") or [])))
    return {"ok": True}


@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: int):
    with session() as conn:
        conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
    return {"ok": True}


# ---------- statements ----------

@app.get("/api/statement")
def get_statement(month: str):
    with session() as conn:
        return metrics.statement(conn, month)


@app.get("/api/statement-files")
def statement_files():
    with session() as conn:
        return files.list_statements(conn)


@app.post("/api/statement-files")
async def upload_statement(file: UploadFile = File(...), institution: str = Form(""), period: str = Form("")):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF statement.")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        with session() as conn:
            return files.index_pdf(conn, tmp_path, file.filename, institution, period)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/api/statement-files/{sid}/pdf")
def statement_pdf(sid: int):
    with session() as conn:
        r = conn.execute("SELECT stored_path, filename FROM statement_files WHERE id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404)
    return FileResponse(r["stored_path"], media_type="application/pdf", filename=r["filename"],
                        content_disposition_type="inline")


@app.delete("/api/statement-files/{sid}")
def delete_statement(sid: int):
    with session() as conn:
        files.delete_statement(conn, sid)
    return {"ok": True}


@app.get("/api/statement-search")
def statement_search(q: str):
    with session() as conn:
        return files.search_statements(conn, q)


@app.post("/api/import-csv")
async def import_csv(account_id: str = Form(...), flip_sign: bool = Form(False), file: UploadFile = File(...)):
    with session() as conn:
        return files.import_csv(conn, account_id, await file.read(), flip_sign)


# ---------- Plaid ----------

@app.post("/api/plaid/link-token")
def link_token(body: dict = Body(default={})):
    if not plaid_sync.configured():
        raise HTTPException(400, "Add PLAID_CLIENT_ID and PLAID_SECRET to .env first.")
    try:
        return {"link_token": plaid_sync.create_link_token(body.get("mode", "banking"), body.get("institution_id"))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Plaid error: {getattr(e, 'body', e)}")


@app.post("/api/plaid/exchange")
def exchange(body: dict = Body(...)):
    try:
        return {"ok": True, "institution_id": plaid_sync.exchange_public_token(body["public_token"])}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Plaid error: {getattr(e, 'body', e)}")


@app.post("/api/sync")
def sync():
    if not plaid_sync.configured():
        return {"ok": True, "note": "No Plaid keys configured; nothing to sync."}
    return plaid_sync.sync_all()


# ---------- demo ----------

@app.post("/api/demo")
def seed_demo():
    demo.seed()
    return {"ok": True}


@app.delete("/api/demo")
def remove_demo():
    with session() as conn:
        demo.remove(conn)
    return {"ok": True}


# ---------- AI ----------

@app.post("/api/chat")
def chat(body: dict = Body(...)):
    try:
        return ai.chat(body.get("messages", []))
    except Exception as e:  # noqa: BLE001
        return {"reply": f"The AI request failed: {e}", "steps": []}
