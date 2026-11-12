"""Fake demo data shaped like your real setup, so you can try the portal before connecting anything.
Every figure here is made up. Remove it from Settings → 'Remove demo data'."""
import datetime as dt
import json
import random

from .categorize import classify
from .db import session

ACCOUNTS = [
    # inst_id, inst_name, acc_id, name, type, subtype, mask, start_balance, limit
    ("demo_chase", "Chase", "demo_chase_chk", "Chase Total Checking", "depository", "checking", "1111", 4200, None),
    ("demo_chase", "Chase", "demo_chase_csr", "Sapphire Reserve", "credit", "credit card", "2222", 0, 30000),
    ("demo_chase", "Chase", "demo_chase_amz", "Prime Visa (Amazon)", "credit", "credit card", "3333", 0, 12000),
    ("demo_bofa", "Bank of America", "demo_bofa_chk", "BofA Advantage Checking", "depository", "checking", "4444", 2100, None),
    ("demo_amex", "American Express", "demo_amex", "Amex Gold Card", "credit", "credit card", "5555", 0, None),
    ("demo_cap1", "Capital One", "demo_cap1", "Venture Rewards", "credit", "credit card", "6666", 0, 15000),
    ("demo_wf", "Wealthfront", "demo_wf_cash", "Wealthfront Cash Account", "depository", "savings", "7777", 9000, None),
    ("demo_webull", "Webull", "demo_webull", "Webull Individual Brokerage", "investment", "brokerage", "8888", 6000, None),
]

GROCERY = ["Trader Joe's", "Key Food", "Whole Foods Market", "Fairway Market", "CTown Supermarkets"]
DINING = ["Chipotle", "Sweetgreen", "Shake Shack", "Local Diner", "Joe's Pizza", "Starbucks", "Dunkin'"]
SHOP = ["Target", "Best Buy", "Uniqlo", "Nike", "Home Depot"]
SUBS = [("Netflix", 15.49), ("Spotify", 11.99), ("iCloud+", 2.99), ("NYSC Gym", 39.99)]


def seed(months: int = 7) -> None:
    rnd = random.Random(42)
    today = dt.date.today()
    start = (today.replace(day=1) - dt.timedelta(days=31 * (months - 1))).replace(day=1)
    bal = {a[2]: float(a[7]) for a in ACCOUNTS}
    is_asset = {a[2]: a[4] not in ("credit", "loan") for a in ACCOUNTS}
    txs, history = [], []
    n = 0

    def add(day, acc, name, amount, primary=None, category=None):
        nonlocal n
        n += 1
        kind, cat = classify(amount, primary, name)
        if category:
            cat = category
        txs.append((f"demo_tx_{n}", acc, day.isoformat(), name, name.split(" PAYROLL")[0].title()
                    if "PAYROLL" in name else name, round(amount, 2), cat, kind))
        # balances: asset += amount; credit owed -= amount
        bal[acc] += amount if is_asset[acc] else -amount

    day = start
    while day <= today:
        d = day.day
        # income
        if day.weekday() == 4 and (day - start).days // 7 % 2 == 0:
            add(day, "demo_chase_chk", "ACME LAW LLP PAYROLL", 2600 + rnd.choice([0, 0, 25.5]), "INCOME")
            add(day, "demo_bofa_chk", "STAFFING CO PAYROLL", 1500 + rnd.uniform(-40, 40), "INCOME")
        # bills
        if d == 1:
            add(day, "demo_chase_chk", "RENT PAYMENT - STEVENSON COMMONS", -1850, "RENT_AND_UTILITIES")
        if d == 6:
            add(day, "demo_bofa_chk", "CON EDISON", -rnd.uniform(70, 135), "RENT_AND_UTILITIES")
        if d == 9:
            add(day, "demo_bofa_chk", "VERIZON WIRELESS", -85.00, "RENT_AND_UTILITIES")
        if d == 12:
            add(day, "demo_cap1", "SPECTRUM INTERNET", -69.99, "RENT_AND_UTILITIES")
        for i, (nm, amt) in enumerate(SUBS):
            if d == 3 + i * 4:
                add(day, "demo_amex", nm, -amt, "ENTERTAINMENT" if nm != "NYSC Gym" else "PERSONAL_CARE")
        # savings & investing (transfers)
        if d == 16:
            add(day, "demo_chase_chk", "ONLINE TRANSFER TO WEALTHFRONT", -1200, "TRANSFER_OUT")
            add(day, "demo_wf_cash", "TRANSFER FROM CHASE", 1200, "TRANSFER_IN")
            add(day, "demo_bofa_chk", "TRANSFER TO WEBULL", -400, "TRANSFER_OUT")
            add(day, "demo_webull", "DEPOSIT FROM BANK OF AMERICA", 400, "TRANSFER_IN")
        if d == 28:
            add(day, "demo_wf_cash", "INTEREST PAYMENT", bal["demo_wf_cash"] * 0.033 / 12, "INCOME")
        # card payments (pay full statement balance)
        for acc, payer, pd in (("demo_chase_csr", "demo_chase_chk", 20), ("demo_chase_amz", "demo_chase_chk", 22),
                               ("demo_amex", "demo_bofa_chk", 24), ("demo_cap1", "demo_bofa_chk", 25)):
            if d == pd and bal[acc] > 0:
                amt = round(bal[acc], 2)
                add(day, payer, f"CREDIT CARD PAYMENT - {acc.split('_')[-1].upper()}", -amt, "LOAN_PAYMENTS")
                add(day, acc, "PAYMENT THANK YOU", amt, "LOAN_PAYMENTS")
        # everyday spending
        if rnd.random() < 0.30:
            add(day, "demo_chase_csr", rnd.choice(GROCERY), -rnd.uniform(25, 110), "FOOD_AND_DRINK", "Groceries")
        if rnd.random() < 0.65:
            add(day, rnd.choice(["demo_chase_csr", "demo_amex"]), rnd.choice(DINING), -rnd.uniform(8, 55),
                "FOOD_AND_DRINK")
        if rnd.random() < 0.22:
            add(day, "demo_chase_csr", rnd.choice(["Uber", "Lyft"]), -rnd.uniform(14, 42), "TRANSPORTATION")
        if d in (1, 15):
            add(day, "demo_chase_chk", "MTA OMNY", -34, "TRANSPORTATION")
        if rnd.random() < 0.18:
            add(day, "demo_chase_amz", "Amazon.com", -rnd.uniform(12, 140), "GENERAL_MERCHANDISE")
        if rnd.random() < 0.05:
            add(day, "demo_cap1", rnd.choice(SHOP), -rnd.uniform(30, 220), "GENERAL_MERCHANDISE")
        if rnd.random() < 0.02:
            add(day, "demo_chase_csr", rnd.choice(["Delta Air Lines", "JetBlue", "Marriott Hotels"]),
                -rnd.uniform(180, 520), "TRAVEL")
        if rnd.random() < 0.01:
            add(day, "demo_chase_amz", "Amazon.com REFUND", rnd.uniform(15, 60), "GENERAL_MERCHANDISE", "Shopping")
        # market moves for the brokerage (not a transaction, just value)
        bal["demo_webull"] *= 1 + rnd.gauss(0.0004, 0.009)
        for a in bal:
            history.append((day.isoformat(), a, round(bal[a], 2)))
        day += dt.timedelta(days=1)

    with session() as conn:
        remove(conn)
        for inst_id, inst_name in {(a[0], a[1]) for a in ACCOUNTS}:
            conn.execute("INSERT INTO institutions (id, name, provider, is_demo, last_synced) "
                         "VALUES (?,?,?,1,datetime('now'))",
                         (inst_id, inst_name, "manual" if inst_id == "demo_webull" else "demo"))
        for a in ACCOUNTS:
            conn.execute("""INSERT INTO accounts (id, institution_id, name, mask, type, subtype, current_balance,
                            credit_limit, is_asset, updated_at) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))""",
                         (a[2], a[0], a[3], a[6], a[4], a[5], round(bal[a[2]], 2), a[8], int(is_asset[a[2]])))
        conn.executemany("INSERT INTO transactions (id, account_id, date, name, merchant, amount, category, kind, source) "
                         "VALUES (?,?,?,?,?,?,?,?,'demo')", txs)
        conn.executemany("INSERT OR REPLACE INTO balance_history VALUES (?,?,?)", history)
        conn.executemany("INSERT INTO holdings VALUES ('demo_webull',?,?,?,?,?,datetime('now'))", [
            ("Vanguard S&P 500 ETF", "VOO", 9.2, None, 4300), ("Invesco QQQ Trust", "QQQ", 4.1, None, 2100),
            ("Microsoft Corp", "MSFT", 3.0, None, 1250), ("Cash", None, None, None, None)])
        # set holding values to match account value roughly
        v = bal["demo_webull"]
        for sec, w in (("VOO", .52), ("QQQ", .28), ("MSFT", .15)):
            conn.execute("UPDATE holdings SET value=? WHERE account_id='demo_webull' AND ticker=?", (round(v * w, 2), sec))
        conn.execute("UPDATE holdings SET value=? WHERE account_id='demo_webull' AND ticker IS NULL", (round(v * .05, 2),))
        if not conn.execute("SELECT 1 FROM goals").fetchone():
            conn.execute("INSERT INTO goals (name, target_amount, target_date, metric, is_demo) VALUES (?,?,?,?,1)",
                         ("Net worth $150K", 150000, f"{today.year + 2}-12-31", "net_worth"))
            conn.execute("INSERT INTO goals (name, target_amount, target_date, metric, account_ids, is_demo) "
                         "VALUES (?,?,?,?,?,1)",
                         ("Emergency fund (6 months)", 25000, f"{today.year + 1}-06-30", "accounts",
                          json.dumps(["demo_wf_cash"])))


def remove(conn) -> None:
    conn.execute("DELETE FROM institutions WHERE is_demo=1")
    conn.execute("DELETE FROM goals WHERE is_demo=1")
    # goals that only pointed at demo accounts
    for g in conn.execute("SELECT id, account_ids FROM goals WHERE metric='accounts'").fetchall():
        ids = json.loads(g["account_ids"] or "[]")
        if ids and all(i.startswith("demo_") for i in ids):
            conn.execute("DELETE FROM goals WHERE id=?", (g["id"],))
