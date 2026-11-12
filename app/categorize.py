"""Turn raw transactions into income / spending / transfer with a readable category."""

# Plaid personal_finance_category.primary -> friendly name
FRIENDLY = {
    "INCOME": "Income",
    "TRANSFER_IN": "Transfer",
    "TRANSFER_OUT": "Transfer",
    "LOAN_PAYMENTS": "Loan & Card Payments",
    "BANK_FEES": "Bank Fees",
    "ENTERTAINMENT": "Entertainment",
    "FOOD_AND_DRINK": "Food & Drink",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Home",
    "MEDICAL": "Medical",
    "PERSONAL_CARE": "Personal Care",
    "GENERAL_SERVICES": "Services",
    "GOVERNMENT_AND_NON_PROFIT": "Taxes, Gov & Giving",
    "TRANSPORTATION": "Transportation",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Rent & Utilities",
}

TRANSFER_PRIMARIES = {"TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS"}

TRANSFER_WORDS = ("payment thank you", "autopay", "online transfer", "transfer to", "transfer from",
                  "credit card payment", "epay", "wealthfront", "webull", "zelle to yourself")


def classify(amount: float, primary: str | None, name: str = "") -> tuple[str, str]:
    """Return (kind, category). amount: + in, - out."""
    primary = (primary or "").upper()
    lname = (name or "").lower()
    if primary == "INCOME":
        return "income", "Income"
    if primary in TRANSFER_PRIMARIES:
        return "transfer", FRIENDLY.get(primary, "Transfer")
    if not primary:
        if any(w in lname for w in TRANSFER_WORDS):
            return "transfer", "Transfer"
        if amount > 0 and any(w in lname for w in ("payroll", "direct dep", "salary", "interest", "dividend")):
            return "income", "Income"
    if amount > 0 and not primary:
        # money in that isn't clearly income: likely a refund -> reduces spending
        return "spending", "Refunds"
    return "spending", FRIENDLY.get(primary, primary.title().replace("_", " ") if primary else "Uncategorized")


def apply_rules(conn, tx: dict) -> dict:
    text = f"{tx.get('name') or ''} {tx.get('merchant') or ''}".lower()
    for r in conn.execute("SELECT pattern, category, kind FROM category_rules ORDER BY id"):
        if r["pattern"].lower() in text:
            if r["category"]:
                tx["category"] = r["category"]
            if r["kind"]:
                tx["kind"] = r["kind"]
    return tx
