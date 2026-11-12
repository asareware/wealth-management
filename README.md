# Wealth Portal

A private dashboard that runs on your own computer. It pulls in all your bank, card and investment accounts and shows:

- **Net worth**: everything you own minus everything you owe, tracked over time
- **Money in vs. money out**: income, spending and what you saved, for today, this week, this month, last month or this year
- **Spending breakdown**: by category and merchant, plus daily spending
- **Transaction search**: across every account at once, with CSV export
- **Statements**: your own monthly statement built from all your accounts (print or save it as a PDF). You can also upload the PDF statements your banks give you and search inside them.
- **Goals**: how far you are, how much you need to save each month, and whether your current pace gets you there
- **Ask AI**: questions in plain English, like "How much did I spend today?" or "How far am I from my goal?"

The code can live anywhere, including OneDrive. Your data (the database and uploaded statements) is kept in `~/WealthPortalData`, outside OneDrive, so it never syncs to the cloud. You can change that with `WEALTH_DATA_DIR` in `.env`. The portal only listens on `127.0.0.1`, so nobody else on your network can open it.

---

## 1. Install (about 5 minutes)

You need **Python 3.10 or newer** (check with `python3 --version`; download it from python.org if you don't have it).

```bash
cd wealth-portal
python3 -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
python run.py
```

Your browser opens at **http://127.0.0.1:8765**. To try it before connecting anything, go to **Connect & settings → Load demo data**. All the demo numbers are made up.

Next time, just run `start.sh` (Mac/Linux) or `start.bat` (Windows).

---

## 2. Connect your real accounts (Plaid, free)

Plaid is the service most finance apps use to connect to banks. Its free **Trial plan** gives you real production data for up to **10 connections**, and it includes Chase, Bank of America and other OAuth banks. You need about 6:

| Connection | Accounts it brings in |
|---|---|
| Chase | Total Checking, Sapphire Reserve, Amazon Prime Visa (one login) |
| Bank of America | Checking |
| American Express | Your Amex card |
| Capital One | Venture card |
| Wealthfront | Cash account (and any investment accounts) |
| Webull | Brokerage (see note below) |

Steps:

1. Sign up at **https://dashboard.plaid.com/signup**. A new team gets the free Trial plan.
2. In the dashboard, open **Developers → Keys** and copy your **client_id** and **production secret**.
3. Under **Link → Link Customization**, pick a use-case description (Plaid requires this). "Personal finance management" fits.
4. Put the keys in `.env`:
   ```
   PLAID_CLIENT_ID=...
   PLAID_SECRET=...
   PLAID_ENV=production
   ```
5. Restart (`Ctrl+C`, then `python run.py`). Go to **Connect & settings → Connect bank or card** and log in to each bank in the Plaid window. For Webull, use **Connect investment account**.
6. Once your real accounts show up, click **Remove demo data**.

The portal pulls up to 2 years of history the first time. After that it syncs every 6 hours while it's running, and you can also click **Sync now**. If a bank asks you to log in again, a **Re-login** button appears next to it.

**Webull note.** Webull's connection through aggregators has been unreliable. If it doesn't show up in Plaid, or it links but shows $0, click **Add manual account** (type: Investment) and update the balance from the Accounts page whenever you like. You can also import a CSV of its activity. Either way it still counts toward your net worth and goals.

**HSA note.** Wealthfront offers cash accounts and investment accounts, not HSAs. If you have an HSA somewhere else (often through your employer's benefits provider), connect it the same way. If Plaid can't find the provider, add it as a manual account.

---

## 3. Turn on the AI assistant (optional)

1. Get an API key at **https://console.anthropic.com** (pay-as-you-go; a typical question costs a fraction of a cent to a few cents).
2. Add it to `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
3. Restart.

**How it works:** the assistant answers by running **read-only** queries against your local database. The database is opened read-only, and anything other than a single SELECT is blocked. The numbers needed for each answer, plus your account names and balances, are sent to Anthropic's API. Your bank logins and Plaid keys never are.

---

## 4. Statements

- **Your own statement:** Statements → pick a month. It shows opening and closing net worth, money in by source, spending by category, totals per account and every transaction. Use **Print / save PDF** to keep a copy.
- **Bank PDFs:** Download statements from each bank's website and upload them (you can select several at once). They're copied into `~/WealthPortalData/statements/` and indexed, so you can search for things like "annual fee" or "interest charged" across all of them. The AI can search them too. Scanned image-only PDFs can't be searched.

---

## How the numbers work

- **Spending** = purchases, bills and fees. Refunds reduce it.
- **Transfers are not spending.** Credit-card payments and moves between your own accounts (checking → Wealthfront, BofA → Webull) are marked *transfer*, so nothing is counted twice. A card purchase counts once, when you make it, not again when you pay the card.
- **Income** = paychecks, interest, dividends and other money in.
- **Net worth** = cash + investments − credit-card balances − loans.
- **Goal pace:** a net-worth goal uses your average (income − spending) over the last 3 full months. An account goal (for example, "Emergency fund in Wealthfront") uses how fast those accounts actually grew over the last 3 months.

If something is categorized wrong, click its category on the Transactions page to change it. Or add a **category rule** in Settings (for example, anything containing "ZELLE" from your own name → transfer). Rules apply to past and future transactions.

---

## Security checklist

- The portal only listens on `127.0.0.1` (your computer). Don't change `HOST` to `0.0.0.0` unless you know why you need to.
- `~/WealthPortalData/wealth.db` holds your Plaid access tokens and all your transactions. Keep FileVault on, and don't move this folder into OneDrive or any other synced or shared folder.
- `.env` holds your keys. Don't share it or commit it to Git.
- Back up by copying `~/WealthPortalData` to an encrypted external drive.
- To disconnect a bank: Connect & settings → **Disconnect**. This also revokes the connection at Plaid.

## Files

```
run.py              start the server
app/main.py         web API
app/plaid_sync.py   Plaid connect + sync
app/metrics.py      net worth, cash flow, goals, statements
app/ai.py           AI assistant (tool use over read-only SQL)
app/files.py        PDF statement search + CSV import
app/categorize.py   income / spending / transfer rules
app/demo.py         fake demo data
static/             the dashboard (HTML/CSS/JS, no build step)
~/WealthPortalData/ your database + uploaded statements (created on first run, outside OneDrive)
```
