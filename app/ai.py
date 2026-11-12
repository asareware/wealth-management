"""AI assistant: Claude answers questions by querying your local database through tools."""
import datetime as dt
import json
import re

from . import config, metrics
from .db import connect, rows
from .files import search_statements

SCHEMA_DOC = """
Tables (SQLite):
- institutions(id, name, provider, last_synced, status)
- accounts(id, institution_id, name, official_name, mask, type, subtype, current_balance,
           available_balance, credit_limit, is_asset, hidden)
    type: depository | credit | investment | loan. For credit cards current_balance = amount OWED.
    is_asset = 0 for credit cards/loans. Always filter hidden = 0.
- transactions(id, account_id, date 'YYYY-MM-DD', name, merchant, amount, category, category_detail,
               kind, pending, source)
    amount: money IN is POSITIVE, money OUT is NEGATIVE.
    kind: 'income' | 'spending' | 'transfer'. Transfers (card payments, moves to savings/brokerage)
    are NOT spending or income — exclude them from spending/income totals.
    Spending total = -SUM(amount) WHERE kind='spending' (refunds are positive and reduce it).
- balance_history(date, account_id, balance)  -- daily snapshots, use for trends
- holdings(account_id, security, ticker, quantity, value, cost_basis)
- goals(id, name, target_amount, target_date, metric, account_ids)
- statement_files(id, filename, institution, period, pages)  -- uploaded bank PDF statements
"""

TOOLS = [
    {
        "name": "run_sql",
        "description": "Run ONE read-only SQLite SELECT query against the user's finance database. "
                       "Returns up to 200 rows as JSON. Use for any specific question about transactions, "
                       "merchants, accounts, balances or holdings." + SCHEMA_DOC,
        "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
    },
    {
        "name": "get_summary",
        "description": "Pre-computed summary for a period: income, spending, net savings, savings rate, "
                       "spending by category, top merchants, income sources, and current net worth. "
                       "period: today | week | month | last_month | last_30 | ytd | YYYY-MM | YYYY-MM-DD:YYYY-MM-DD",
        "input_schema": {"type": "object", "properties": {"period": {"type": "string"}}, "required": ["period"]},
    },
    {
        "name": "get_goals",
        "description": "Progress toward the user's saved goals: current amount, remaining, percent, "
                       "required monthly saving to hit the target date, the user's actual average monthly "
                       "savings over the last 3 full months, projected completion date, and on_track.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_statements",
        "description": "Full-text search across the bank PDF statements the user uploaded. "
                       "Returns file, page and a text snippet.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
]

FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum)\b", re.I)


def _run_sql(sql: str) -> dict:
    sql = sql.strip().rstrip(";")
    if ";" in sql or FORBIDDEN.search(sql) or not re.match(r"^\s*(select|with)\b", sql, re.I):
        return {"error": "Only a single SELECT query is allowed."}
    conn = connect(readonly=True)  # opened read-only at the SQLite level too
    try:
        cur = conn.execute(sql)
        data = [dict(r) for r in cur.fetchmany(200)]
        return {"rows": data, "row_count": len(data), "truncated": len(data) == 200}
    except Exception as e:  # noqa: BLE001 - return the error to the model so it can fix the query
        return {"error": str(e)}
    finally:
        conn.close()


def _call_tool(name: str, args: dict) -> dict:
    conn = connect(readonly=True)
    try:
        if name == "run_sql":
            return _run_sql(args.get("sql", ""))
        if name == "get_summary":
            p = args.get("period", "month")
            s, e = metrics.period_range(p)
            return {"period": p, "range": [s, e], "cash_flow": metrics.cash_flow(conn, s, e),
                    "spending_by_category": metrics.spending_by_category(conn, s, e),
                    "top_merchants": metrics.top_merchants(conn, s, e),
                    "income_sources": metrics.income_sources(conn, s, e),
                    "net_worth_now": metrics.net_worth(conn)}
        if name == "get_goals":
            return {"goals": metrics.goal_progress(conn)}
        if name == "search_statements":
            return {"results": search_statements(conn, args.get("query", ""))}
        return {"error": f"unknown tool {name}"}
    finally:
        conn.close()


def _system_prompt() -> str:
    conn = connect(readonly=True)
    try:
        accs = rows(conn, """SELECT a.name, i.name AS institution, a.type, a.subtype, a.mask,
                                    ROUND(a.current_balance,2) AS balance
                             FROM accounts a JOIN institutions i ON i.id=a.institution_id WHERE a.hidden=0""")
    finally:
        conn.close()
    today = dt.date.today()
    return f"""You are the assistant inside the user's private, local wealth portal. Today is {today.isoformat()} ({today:%A}).
You answer questions about the user's own money using the tools. Always get real numbers from the tools;
never guess or invent figures. Prefer get_summary / get_goals for standard questions and run_sql for specific ones.

Conventions: money in is positive, money out is negative; transfers between the user's own accounts and
credit-card payments are kind='transfer' and are neither income nor spending.

Answer in plain English, short and direct: lead with the number, then one or two lines of context
(e.g. compared with usual, biggest items). Format money like $1,234.56. If data is missing (no transactions
for a period, account not connected), say so plainly. You can give general observations, but you are not a
licensed financial advisor, so frame suggestions as options, not instructions.

Connected accounts right now:
{json.dumps(accs, indent=0)}
{SCHEMA_DOC}"""


def chat(messages: list[dict]) -> dict:
    """messages: [{role: 'user'|'assistant', content: str}, ...] -> {reply, steps}"""
    if not config.ANTHROPIC_API_KEY:
        return {"reply": "The AI assistant needs an Anthropic API key. Add ANTHROPIC_API_KEY to your .env "
                         "file and restart the portal.", "steps": []}
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    convo = [{"role": m["role"], "content": m["content"]} for m in messages[-20:]]
    steps = []
    system = _system_prompt()
    for _ in range(8):  # tool-use loop
        resp = client.messages.create(model=config.AI_MODEL, max_tokens=1500, system=system,
                                      tools=TOOLS, messages=convo)
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return {"reply": text or "(no answer)", "steps": steps}
        blocks = []
        for b in resp.content:  # echo back only the fields the API expects
            if b.type == "text":
                blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        convo.append({"role": "assistant", "content": blocks})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                out = _call_tool(b.name, b.input)
                steps.append({"tool": b.name, "input": b.input})
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, default=str)[:30000]})
        convo.append({"role": "user", "content": results})
    return {"reply": "That question took too many steps. Try asking it more specifically.", "steps": steps}
