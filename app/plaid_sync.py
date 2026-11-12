"""Plaid: Link tokens, token exchange, and syncing accounts / transactions / holdings."""
import datetime as dt
import uuid

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.link_token_transactions import LinkTokenTransactions
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from . import config, crypto
from .categorize import apply_rules, classify
from .db import session


def configured() -> bool:
    return bool(config.PLAID_CLIENT_ID and config.PLAID_SECRET)


def _client() -> plaid_api.PlaidApi:
    host = plaid.Environment.Sandbox if config.PLAID_ENV == "sandbox" else plaid.Environment.Production
    cfg = plaid.Configuration(host=host, api_key={"clientId": config.PLAID_CLIENT_ID,
                                                  "secret": config.PLAID_SECRET})
    return plaid_api.PlaidApi(plaid.ApiClient(cfg))


def create_link_token(mode: str = "banking", update_institution_id: str | None = None) -> str:
    """mode 'banking' = checking/savings/cards; 'investments' = brokerages like Webull."""
    kwargs = dict(
        client_name="My Wealth Portal",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id="owner"),
    )
    if update_institution_id:  # re-login flow when a bank connection expires
        with session() as conn:
            row = conn.execute("SELECT access_token FROM institutions WHERE id=?",
                               (update_institution_id,)).fetchone()
        kwargs["access_token"] = crypto.decrypt(row["access_token"])
    elif mode == "investments":
        kwargs["products"] = [Products("investments")]
    else:
        kwargs["products"] = [Products("transactions")]
        kwargs["optional_products"] = [Products("investments")]
        kwargs["transactions"] = LinkTokenTransactions(days_requested=730)
    if config.PLAID_REDIRECT_URI:
        kwargs["redirect_uri"] = config.PLAID_REDIRECT_URI
    resp = _client().link_token_create(LinkTokenCreateRequest(**kwargs))
    return resp["link_token"]


def exchange_public_token(public_token: str) -> str:
    crypto.ensure_key()  # check first: once exchanged, the token must be stored encrypted
    client = _client()
    resp = client.item_public_token_exchange(ItemPublicTokenExchangeRequest(public_token=public_token))
    access_token, item_id = resp["access_token"], resp["item_id"]
    item = client.item_get(ItemGetRequest(access_token=access_token))["item"]
    name = "Linked institution"
    if item.get("institution_id"):
        try:
            inst = client.institutions_get_by_id(InstitutionsGetByIdRequest(
                institution_id=item["institution_id"], country_codes=[CountryCode("US")]))
            name = inst["institution"]["name"]
        except plaid.ApiException:
            pass
    products = sorted({str(p) for p in (item.get("products") or [])} |
                      {str(p) for p in (item.get("consented_products") or [])})
    with session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO institutions (id, name, provider, access_token, products) "
            "VALUES (?,?,?,?,?)", (item_id, name, "plaid", crypto.encrypt(access_token), ",".join(products)))
    sync_institution(item_id)
    return item_id


def remove_institution(inst_id: str) -> None:
    with session() as conn:
        row = conn.execute("SELECT provider, access_token FROM institutions WHERE id=?", (inst_id,)).fetchone()
        if row and row["provider"] == "plaid" and row["access_token"] and configured():
            try:
                _client().item_remove(ItemRemoveRequest(access_token=crypto.decrypt(row["access_token"])))
            except plaid.ApiException:
                pass
        conn.execute("DELETE FROM institutions WHERE id=?", (inst_id,))


def _num(v):
    return float(v) if v is not None else None


def _upsert_accounts(conn, inst_id: str, accounts) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    today = dt.date.today().isoformat()
    for a in accounts:
        typ = str(a["type"])
        bal = a["balances"]
        is_asset = 0 if typ in ("credit", "loan") else 1
        current = _num(bal.get("current")) or 0.0
        conn.execute(
            """INSERT INTO accounts (id, institution_id, name, official_name, mask, type, subtype,
                   current_balance, available_balance, credit_limit, currency, is_asset, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET current_balance=excluded.current_balance,
                   available_balance=excluded.available_balance, credit_limit=excluded.credit_limit,
                   official_name=excluded.official_name, updated_at=excluded.updated_at""",
            (a["account_id"], inst_id, a["name"], a.get("official_name"), a.get("mask"), typ,
             str(a.get("subtype") or ""), current, _num(bal.get("available")), _num(bal.get("limit")),
             bal.get("iso_currency_code") or "USD", is_asset, now))
        conn.execute("INSERT OR REPLACE INTO balance_history (date, account_id, balance) VALUES (?,?,?)",
                     (today, a["account_id"], current))


def _tx_row(conn, t) -> dict:
    pfc = t.get("personal_finance_category") or {}
    primary = pfc.get("primary") if pfc else None
    amount = -float(t["amount"])  # Plaid: positive = money out. We flip it.
    kind, category = classify(amount, primary, t.get("name") or "")
    row = {
        "id": t["transaction_id"], "account_id": t["account_id"], "date": str(t["date"]),
        "name": t.get("name"), "merchant": t.get("merchant_name"), "amount": amount,
        "category": category, "category_detail": (pfc.get("detailed") if pfc else None),
        "kind": kind, "pending": 1 if t.get("pending") else 0,
    }
    return apply_rules(conn, row)


def sync_institution(inst_id: str) -> dict:
    client = _client()
    with session() as conn:
        inst = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
        token, cursor = crypto.decrypt(inst["access_token"]), inst["cursor"]
        products = (inst["products"] or "").split(",")
    added = modified = removed = 0
    try:
        accounts = client.accounts_get(AccountsGetRequest(access_token=token))["accounts"]
        with session() as conn:
            _upsert_accounts(conn, inst_id, accounts)

        if "transactions" in products:
            has_more = True
            while has_more:
                req = TransactionsSyncRequest(access_token=token, count=500)
                if cursor:
                    req = TransactionsSyncRequest(access_token=token, cursor=cursor, count=500)
                resp = client.transactions_sync(req)
                with session() as conn:
                    for t in list(resp["added"]) + list(resp["modified"]):
                        r = _tx_row(conn, t)
                        conn.execute(
                            """INSERT INTO transactions (id, account_id, date, name, merchant, amount, category,
                                   category_detail, kind, pending, source)
                               VALUES (:id,:account_id,:date,:name,:merchant,:amount,:category,
                                   :category_detail,:kind,:pending,'plaid')
                               ON CONFLICT(id) DO UPDATE SET date=excluded.date, name=excluded.name,
                                   merchant=excluded.merchant, amount=excluded.amount,
                                   pending=excluded.pending""", r)
                    for t in resp["removed"]:
                        conn.execute("DELETE FROM transactions WHERE id=?", (t["transaction_id"],))
                    added += len(resp["added"]); modified += len(resp["modified"]); removed += len(resp["removed"])
                    cursor = resp["next_cursor"]
                    conn.execute("UPDATE institutions SET cursor=? WHERE id=?", (cursor, inst_id))
                has_more = resp["has_more"]

        if "investments" in products:
            try:
                h = client.investments_holdings_get(InvestmentsHoldingsGetRequest(access_token=token))
                secs = {s["security_id"]: s for s in h["securities"]}
                now = dt.datetime.now().isoformat(timespec="seconds")
                with session() as conn:
                    ids = {x["account_id"] for x in h["accounts"]}
                    for aid in ids:
                        conn.execute("DELETE FROM holdings WHERE account_id=?", (aid,))
                    for x in h["holdings"]:
                        s = secs.get(x["security_id"], {})
                        conn.execute(
                            "INSERT INTO holdings VALUES (?,?,?,?,?,?,?)",
                            (x["account_id"], s.get("name"), s.get("ticker_symbol"), _num(x.get("quantity")),
                             _num(x.get("institution_value")), _num(x.get("cost_basis")), now))
            except plaid.ApiException:
                pass  # institution may not support holdings

        with session() as conn:
            conn.execute("UPDATE institutions SET last_synced=datetime('now'), status='ok' WHERE id=?", (inst_id,))
        return {"ok": True, "added": added, "modified": modified, "removed": removed}
    except plaid.ApiException as e:
        status = "needs_relogin" if "ITEM_LOGIN_REQUIRED" in str(e.body) else "error"
        with session() as conn:
            conn.execute("UPDATE institutions SET status=? WHERE id=?", (status, inst_id))
        return {"ok": False, "error": status, "detail": str(e.body)[:500]}


def sync_all() -> dict:
    with session() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM institutions WHERE provider='plaid'")]
    return {i: sync_institution(i) for i in ids}


def new_id() -> str:
    return uuid.uuid4().hex
