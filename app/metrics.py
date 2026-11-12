"""All the numbers: net worth, cash flow, spending, goals, statements."""
import datetime as dt
import json

from .db import rows


def _today() -> dt.date:
    return dt.date.today()


def period_range(period: str) -> tuple[str, str]:
    """'today' | 'week' | 'month' | 'last_month' | 'ytd' | 'YYYY-MM' | 'YYYY-MM-DD:YYYY-MM-DD'"""
    t = _today()
    if ":" in period:
        a, b = period.split(":")
        return a, b
    if len(period) == 7 and period[4] == "-":
        y, m = map(int, period.split("-"))
        start = dt.date(y, m, 1)
        end = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
        return start.isoformat(), end.isoformat()
    if period == "today":
        return t.isoformat(), t.isoformat()
    if period == "week":
        return (t - dt.timedelta(days=t.weekday())).isoformat(), t.isoformat()
    if period == "last_month":
        first = t.replace(day=1)
        last_end = first - dt.timedelta(days=1)
        return last_end.replace(day=1).isoformat(), last_end.isoformat()
    if period == "ytd":
        return t.replace(month=1, day=1).isoformat(), t.isoformat()
    if period == "last_30":
        return (t - dt.timedelta(days=29)).isoformat(), t.isoformat()
    return t.replace(day=1).isoformat(), t.isoformat()  # 'month'


def accounts(conn) -> list[dict]:
    return rows(conn, """SELECT a.*, i.name AS institution, i.provider, i.status AS institution_status,
                                i.last_synced, i.is_demo
                         FROM accounts a JOIN institutions i ON i.id = a.institution_id
                         WHERE a.hidden = 0
                         ORDER BY a.is_asset DESC, a.type, a.current_balance DESC""")


def net_worth(conn) -> dict:
    accs = accounts(conn)
    assets = sum(a["current_balance"] for a in accs if a["is_asset"])
    debts = sum(a["current_balance"] for a in accs if not a["is_asset"])
    by_type: dict[str, float] = {}
    for a in accs:
        label = {"depository": "Cash", "investment": "Investments", "credit": "Credit cards",
                 "loan": "Loans"}.get(a["type"], "Other")
        by_type[label] = by_type.get(label, 0) + a["current_balance"]
    cash = sum(a["current_balance"] for a in accs if a["type"] == "depository")
    return {"net_worth": round(assets - debts, 2), "assets": round(assets, 2),
            "liabilities": round(debts, 2), "cash": round(cash, 2),
            "by_type": {k: round(v, 2) for k, v in by_type.items()}}


def net_worth_history(conn, days: int = 365) -> list[dict]:
    start = (_today() - dt.timedelta(days=days)).isoformat()
    accs = {a["id"]: a["is_asset"] for a in rows(conn, "SELECT id, is_asset FROM accounts WHERE hidden=0")}
    hist = rows(conn, "SELECT date, account_id, balance FROM balance_history ORDER BY date")
    dates = sorted({h["date"] for h in hist if h["date"] >= start})
    latest: dict[str, float] = {}
    out, i = [], 0
    # walk forward carrying each account's last known balance
    for d in dates:
        while i < len(hist) and hist[i]["date"] <= d:
            if hist[i]["account_id"] in accs:
                latest[hist[i]["account_id"]] = hist[i]["balance"]
            i += 1
        nw = sum(b if accs[a] else -b for a, b in latest.items())
        out.append({"date": d, "net_worth": round(nw, 2)})
    return out


def cash_flow(conn, start: str, end: str) -> dict:
    r = conn.execute("""SELECT
            COALESCE(SUM(CASE WHEN kind='income' THEN amount END),0)   AS income,
            COALESCE(-SUM(CASE WHEN kind='spending' THEN amount END),0) AS spending,
            COUNT(CASE WHEN kind='spending' AND amount<0 THEN 1 END)  AS purchases
        FROM transactions t JOIN accounts a ON a.id=t.account_id
        WHERE a.hidden=0 AND date BETWEEN ? AND ?""", (start, end)).fetchone()
    income, spending = round(r["income"], 2), round(r["spending"], 2)
    return {"start": start, "end": end, "income": income, "spending": spending,
            "net": round(income - spending, 2), "purchases": r["purchases"],
            "savings_rate": round((income - spending) / income * 100, 1) if income else None}


def spending_by_category(conn, start: str, end: str) -> list[dict]:
    return rows(conn, """SELECT category, ROUND(-SUM(amount),2) AS total, COUNT(*) AS count
        FROM transactions t JOIN accounts a ON a.id=t.account_id
        WHERE a.hidden=0 AND kind='spending' AND date BETWEEN ? AND ?
        GROUP BY category HAVING total > 0 ORDER BY total DESC""", (start, end))


def top_merchants(conn, start: str, end: str, limit: int = 10) -> list[dict]:
    return rows(conn, """SELECT COALESCE(t.merchant, t.name) AS merchant, ROUND(-SUM(amount),2) AS total,
               COUNT(*) AS count
        FROM transactions t JOIN accounts a ON a.id=t.account_id
        WHERE a.hidden=0 AND kind='spending' AND date BETWEEN ? AND ?
        GROUP BY COALESCE(t.merchant, t.name) HAVING total > 0 ORDER BY total DESC LIMIT ?""",
                (start, end, limit))


def income_sources(conn, start: str, end: str) -> list[dict]:
    return rows(conn, """SELECT COALESCE(t.merchant, t.name) AS source, ROUND(SUM(amount),2) AS total, COUNT(*) AS count
        FROM transactions t JOIN accounts a ON a.id=t.account_id
        WHERE a.hidden=0 AND kind='income' AND date BETWEEN ? AND ?
        GROUP BY COALESCE(t.merchant, t.name) ORDER BY total DESC""", (start, end))


def monthly_series(conn, months: int = 12) -> list[dict]:
    t = _today()
    out = []
    for k in range(months - 1, -1, -1):
        y, m = t.year, t.month - k
        while m <= 0:
            m += 12; y -= 1
        key = f"{y:04d}-{m:02d}"
        s, e = period_range(key)
        cf = cash_flow(conn, s, e)
        out.append({"month": key, "income": cf["income"], "spending": cf["spending"], "net": cf["net"]})
    return out


def daily_spending(conn, start: str, end: str) -> list[dict]:
    return rows(conn, """SELECT date, ROUND(-SUM(amount),2) AS spending
        FROM transactions t JOIN accounts a ON a.id=t.account_id
        WHERE a.hidden=0 AND kind='spending' AND date BETWEEN ? AND ?
        GROUP BY date ORDER BY date""", (start, end))


def avg_monthly_savings(conn, months: int = 3) -> float:
    """Average (income - spending) over the last N *complete* months."""
    series = monthly_series(conn, months + 1)[:-1]
    series = [s for s in series if s["income"] or s["spending"]]
    return round(sum(s["net"] for s in series) / len(series), 2) if series else 0.0


def goal_progress(conn) -> list[dict]:
    nw = net_worth(conn)
    balances = {a["id"]: a for a in rows(conn, "SELECT id, current_balance, is_asset FROM accounts")}
    pace = avg_monthly_savings(conn)
    out = []
    for g in rows(conn, "SELECT * FROM goals ORDER BY id"):
        g_pace = pace
        if g["metric"] == "accounts" and g["account_ids"]:
            ids = json.loads(g["account_ids"])
            current = sum((balances[i]["current_balance"] if balances[i]["is_asset"]
                           else -balances[i]["current_balance"]) for i in ids if i in balances)
            # pace for an account goal = how fast those accounts actually grew over ~3 months
            then = (_today() - dt.timedelta(days=91)).isoformat()
            past = 0.0
            for i in ids:
                r = conn.execute("SELECT balance FROM balance_history WHERE account_id=? AND date<=? "
                                 "ORDER BY date DESC LIMIT 1", (i, then)).fetchone()
                if r is None:
                    r = conn.execute("SELECT balance FROM balance_history WHERE account_id=? ORDER BY date LIMIT 1",
                                     (i,)).fetchone()
                past += (r["balance"] if r else 0) * (1 if balances.get(i, {}).get("is_asset", 1) else -1)
            g_pace = round((current - past) / 3, 2)
        else:
            current = nw["net_worth"]
        remaining = max(g["target_amount"] - current, 0)
        months_left = needed_per_month = projected = None
        if g["target_date"]:
            td = dt.date.fromisoformat(g["target_date"])
            months_left = max((td.year - _today().year) * 12 + td.month - _today().month, 0)
            needed_per_month = round(remaining / months_left, 2) if months_left else remaining
        if remaining == 0:
            projected = _today().isoformat()
        elif g_pace > 0:
            mths = remaining / g_pace
            projected = (_today() + dt.timedelta(days=int(mths * 30.44))).isoformat()
        on_track = None
        if needed_per_month is not None and remaining > 0:
            on_track = g_pace >= needed_per_month
        out.append({**g, "current": round(current, 2), "remaining": round(remaining, 2),
                    "percent": round(min(current / g["target_amount"] * 100, 100), 1) if g["target_amount"] else 0,
                    "months_left": months_left, "needed_per_month": needed_per_month,
                    "current_pace_per_month": g_pace, "projected_date": projected, "on_track": on_track})
    return out


def _balance_on(conn, day: str) -> float:
    """Net worth using each account's latest balance on or before `day`."""
    r = rows(conn, """SELECT a.is_asset, h.balance FROM accounts a
        JOIN balance_history h ON h.account_id=a.id
        WHERE a.hidden=0 AND h.date = (SELECT MAX(date) FROM balance_history
                                       WHERE account_id=a.id AND date <= ?)""", (day,))
    return round(sum(x["balance"] if x["is_asset"] else -x["balance"] for x in r), 2) if r else None


def statement(conn, month: str) -> dict:
    """Your own monthly statement, built from every connected account."""
    s, e = period_range(month)
    prev_day = (dt.date.fromisoformat(s) - dt.timedelta(days=1)).isoformat()
    per_account = rows(conn, """SELECT a.name, i.name AS institution, a.mask,
            ROUND(SUM(CASE WHEN t.amount>0 THEN t.amount ELSE 0 END),2) AS money_in,
            ROUND(-SUM(CASE WHEN t.amount<0 THEN t.amount ELSE 0 END),2) AS money_out,
            COUNT(t.id) AS count
        FROM accounts a JOIN institutions i ON i.id=a.institution_id
        LEFT JOIN transactions t ON t.account_id=a.id AND t.date BETWEEN ? AND ?
        WHERE a.hidden=0 GROUP BY a.id ORDER BY i.name, a.name""", (s, e))
    txs = rows(conn, """SELECT t.date, COALESCE(t.merchant,t.name) AS description, t.amount, t.category,
               t.kind, a.name AS account FROM transactions t JOIN accounts a ON a.id=t.account_id
        WHERE a.hidden=0 AND t.date BETWEEN ? AND ? ORDER BY t.date, t.amount""", (s, e))
    return {"month": month, "start": s, "end": e,
            "summary": cash_flow(conn, s, e),
            "opening_net_worth": _balance_on(conn, prev_day),
            "closing_net_worth": _balance_on(conn, e),
            "income_sources": income_sources(conn, s, e),
            "spending_by_category": spending_by_category(conn, s, e),
            "top_merchants": top_merchants(conn, s, e),
            "accounts": per_account, "transactions": txs}


def overview(conn, period: str = "month") -> dict:
    s, e = period_range(period)
    t = _today().isoformat()
    return {"period": period, "start": s, "end": e,
            "net_worth": net_worth(conn),
            "cash_flow": cash_flow(conn, s, e),
            "today": cash_flow(conn, t, t),
            "spending_by_category": spending_by_category(conn, s, e),
            "top_merchants": top_merchants(conn, s, e, 8),
            "monthly": monthly_series(conn, 12),
            "net_worth_history": net_worth_history(conn, 365),
            "daily_spending": daily_spending(conn, *period_range("last_30")),
            "goals": goal_progress(conn)}
