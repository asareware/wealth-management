# Wealth Portal Plan: Local to Azure

As of 2026-11-12. Living copy: https://claude.ai/artifact/6wboGKGcbae4LUT6zStsoJ

## Goal

One private web page, reached through a URL and opened with your Azure (Microsoft Entra ID) login, that shows all your money in one place. It covers every connected account, net worth, spending and goals, plus an AI assistant that answers plain questions such as "How much did I spend today?" by querying your data.

- **Who it is for:** you only, for now. It may open to the public later, which would add the work in Phase 5.
- **Where it runs:** first on your own computer for testing, then on Azure App Service.
- **AI:** Claude, reached through Azure Foundry instead of Anthropic directly.

## Where it stands today

The app already works on your own computer. The repo has a Python (FastAPI) server, a SQLite database and a plain HTML/JS dashboard.

| Area | What exists now |
| --- | --- |
| Accounts | Plaid connections (Chase, BofA, Amex, Capital One, Wealthfront, Webull), manual accounts, CSV import |
| Numbers | Net worth over time, money in vs. out by period, spending by category and merchant, goals with pace and projected date |
| Statements | A monthly statement built from all accounts, plus upload and search of bank PDF statements |
| AI | Claude answers questions by running read-only SQL against the local database |
| Security | Listens on your computer only (127.0.0.1); data kept in `~/WealthPortalData`, outside OneDrive; no login |

A test with demo data showed the core numbers work. One gap was found: the AI's SQL tool can read the stored Plaid tokens (fixed in Phase 2).

## Phase 1: Test locally

Test everything at http://127.0.0.1:8765 on your own computer before anything goes online. No code changes are needed for this phase.

- [ ] Install Python 3.10+, create a virtual environment, and run `pip install -r requirements.txt`
- [ ] Copy `.env.example` to `.env` and run `python run.py`
- [ ] Load demo data and check every page: Overview, Transactions, Statements, Goals, Accounts, Ask AI
- [ ] Create a Plaid account (free Trial plan, up to 10 connections) and add the client ID and production secret to `.env`
- [ ] Connect each bank and card, then remove the demo data
- [ ] Check the numbers against your bank sites: balances, a month of spending, card payments counted as transfers
- [ ] Add an Anthropic API key and try questions such as "How much did I spend today?"
- [ ] Note anything miscategorized and add category rules

**Done when:** real balances and transactions match your banks, and the AI answers correctly.

## Phase 2: Security before hosting

Today the app is safe only because nothing outside your computer can reach it. Once it is on a URL, these protections have to be in place first.

| Change | Why | Breaks anything? |
| --- | --- | --- |
| Microsoft Entra ID sign-in, limited to your account | The app has no login; without this, anyone with the URL sees your money | No; it sits in front of the app |
| Block the AI from reading `access_token` and `cursor` | A query like `SELECT * FROM institutions` would send Plaid tokens to the AI service | No; no money question needs those columns |
| Move keys out of `.env` | Plaid and AI keys belong in App Service settings or Key Vault | No; the app reads them the same way |
| Encrypt Plaid tokens in the database | A copied database file would otherwise expose working bank tokens | No; done inside the sync code |

The token block lives in the app's own code, before any result reaches a model, so it protects you the same way with Anthropic or Azure Foundry.

## Phase 3: Host on Azure App Service

The app runs as one Python web app on App Service, with Entra ID sign-in in front of it and its data in App Service's persistent storage.

```
You, in a browser ──► Entra ID sign-in ──► Wealth Portal app (FastAPI on App Service)
                                                   │
                     ┌──────────────┬──────────────┼──────────────┐
                     ▼              ▼              ▼              ▼
              SQLite in /home   Key Vault        Plaid       Azure Foundry
                               (Plaid, AI keys)  (banks)     (Claude for Ask AI)
```

| Setting | Today (local) | On App Service |
| --- | --- | --- |
| Address and port | 127.0.0.1:8765 | All addresses, on the port App Service provides |
| Database | `~/WealthPortalData/wealth.db` | SQLite under `/home`, single instance |
| Statements folder | `~/WealthPortalData/statements` | Under `/home`, or Azure Blob Storage |
| Bank sync every 6 hours | Runs while the app is open | Needs "Always On" (Basic plan or higher) |
| Secrets | `.env` file | App Service settings or Key Vault references |
| Plaid redirect URL | Not needed | Your HTTPS address, registered in the Plaid dashboard |
| Browser auto-open in `run.py` | Opens a tab | Ignored on a server; harmless |

**Done when:** the URL asks for your Microsoft login, refuses any other account, and shows the same numbers as the local test.

## Phase 4: Switch the AI to Azure Foundry

This is a small change in one file, `app/ai.py`. Claude is available on Microsoft Foundry, and the Anthropic Python SDK the app already uses has a Foundry client (`AnthropicFoundry`).

1. Deploy a Claude model in your Foundry resource and note the resource name and deployment name.
2. Swap the client in `app/ai.py` from `Anthropic` to `AnthropicFoundry`.
3. Set the AI model setting to your Foundry deployment name.
4. Store the Foundry key in App Service settings or Key Vault. Signing in with an Azure identity instead of a key still needs to be confirmed.
5. Ask the same test questions as Phase 1 and compare the answers.

The tool-use loop and the read-only SQL tool stay as they are. Your financial data still goes to the model to answer questions, now inside Azure.

## Phase 5 (later): If the app goes public

Opening the app to other people turns a personal tool into a service that holds strangers' bank data, so it needs a separate design pass.

- **Database:** move from SQLite to Azure SQL or Azure Database for PostgreSQL.
- **Per-user data:** every account, transaction, goal and statement tied to a user, and every query (including the AI's) limited to that user.
- **Sign-in:** open Entra ID to outside accounts (for example, Entra External ID).
- **Plaid:** move from the Trial plan to a paid plan, and complete Plaid's production review.
- **Security review:** a full review, plus logging and monitoring, before anyone else's data goes in.

## Open questions

- [ ] Which App Service plan? Always On, needed for the 6-hour bank sync, starts at the Basic tier.
- [ ] Keep SQLite on App Service for the personal phase, or move to Azure SQL or Postgres from the start?
- [ ] Foundry: API key, or an Azure identity (managed identity)?
- [ ] Store uploaded PDF statements under `/home` or in Azure Blob Storage?
- [ ] Keep the app running on your computer as a backup once it is hosted?
