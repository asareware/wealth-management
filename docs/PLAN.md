# Wealth Portal Plan: Local to Azure

Living copy (shared doc): https://claude.ai/artifact/6wboGKGcbae4LUT6zStsoJ
This file is the source of truth for progress. It is updated as each step lands.

## Goal

One private web page, reached through a URL and opened with your Microsoft Entra ID login, that shows all your money in one place: every connected account, net worth, spending, goals, statements, and an AI assistant that answers plain questions such as "How much did I spend today?" by querying your data.

- **Who it is for:** you only, for now. It may open to the public later (see "Later: if the app goes public").
- **Where it runs:** Azure App Service, deployed from GitHub. Local runs are for development only.
- **AI:** Claude, reached through Azure Foundry.
- **Also:** a learning and portfolio project. Claude writes the application code and the infrastructure code (Bicep) with explanations; you run the Azure and Entra ID setup with a step-by-step walkthrough.

## Progress tracker

Status: **Done**, **In progress**, **Next**, **Not started**.

| # | Step | Who | Status |
| --- | --- | --- | --- |
| 0 | Decisions: Bicep, SQLite in `/home`, GitHub Actions, work tenant | You | Done |
| 1 | Production config: settings for host, port and data folder; `/healthz` check; startup command; no browser pop-up on the server | Claude (code) | Done |
| 2 | Security code: AI can't read Plaid tokens; app double-checks the signed-in user; writes need a same-site header (CSRF); Plaid tokens encrypted at rest | Claude (code) | Done |
| 3 | **Lab:** set up Azure Foundry in the portal, deploy Claude, wire it into `app/ai.py` ([lab guide](labs/step-3-azure-foundry.md)) | You, hands-on; Claude provides code and reviews | In progress |
| 4 | Automated tests + a CI workflow that runs them on every push and pull request | Claude (code) | Not started |
| 5 | Bicep templates: App Service plan, web app, Key Vault, managed identity, logging, Entra ID sign-in settings | Claude writes, you review | Not started |
| 6 | Make the GitHub repo private | You | Not started |
| 7 | Entra ID app registration for sign-in, limited to your account | You, guided | Not started |
| 8 | Deploy the Bicep templates to a resource group; put secrets in Key Vault | You, guided | Not started |
| 9 | Passwordless GitHub-to-Azure deploy (OIDC) + deploy workflow | Claude writes the workflow; you create the identity | Not started |
| 10 | Plaid production setup (redirect URL), then connect your banks | You, guided | Not started |
| 11 | Foundry resource + Claude deployment; turn on Ask AI | You, guided | Not started |
| 12 | Go-live checks: other accounts refused, numbers match your banks, first backup taken | Both | Not started |

## Decisions

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-12 | Infrastructure as code with Bicep from the start | Repeatable, reviewable, portfolio-ready |
| 2026-11-12 | SQLite in App Service `/home` storage for the personal phase | No extra cost, almost no code change; fine for one user on one instance |
| 2026-11-12 | Deploy with GitHub Actions on push to `main` | Automatic, auditable deploys; passwordless sign-in to Azure (OIDC) |
| 2026-11-12 | Sign-in through your existing Entra ID work tenant | App Service Authentication handles login before any request reaches the app |
| 2026-11-12 | GitHub is the only home for the code; keys and data never go in the repo | `.env` and data folders are git-ignored; secrets live in Key Vault in production |

## Target architecture

```
You, in a browser ──► Entra ID sign-in ──► Wealth Portal app (FastAPI on App Service, Linux, B1)
  (HTTPS only)        (App Service              │   system-assigned managed identity
                       Authentication)          │
                     ┌──────────────┬───────────┼──────────────┬────────────────┐
                     ▼              ▼           ▼              ▼                ▼
              SQLite in        Key Vault      Plaid       Azure Foundry    App Insights
              /home/data      (Plaid keys,   (banks)     (Claude for      (logs, errors)
              (+ statements)   token key,                  Ask AI)
                               Foundry key)

GitHub (main) ──► GitHub Actions: test, then deploy (OIDC, no stored password) ──► App Service
```

## Step details

### Step 1: Production config (Done)

The same code now runs locally and on App Service; the difference is only in settings.

| Setting | Local default | On App Service (detected automatically) |
| --- | --- | --- |
| Host | `127.0.0.1` (your computer only) | `0.0.0.0` (App Service's front end forwards traffic in) |
| Port | `8765` | `8000` (or `PORT` / `WEBSITES_PORT` if set) |
| Data folder | `~/WealthPortalData` | `/home/data` (the only storage that survives restarts) |
| Browser pop-up | Opens a tab | Off |
| Log level | Warnings | Info (visible in App Service log stream) |

- App Service is detected by the `WEBSITE_SITE_NAME` variable, which App Service sets on every web app.
- `/healthz` answers `{"ok": true}` when the app and database are up. App Service's health check will call it.
- Startup command on App Service: `python run.py` (one process, which the SQLite database and the background bank sync need).

### Step 2: Security code (Done)

| Change | How it works | Where |
| --- | --- | --- |
| The AI can't read `access_token` or `cursor` | A SQLite *authorizer* is asked about every column a query reads and answers "ignore" for these two, so they come back empty even with `SELECT *`, subqueries or CTEs | `app/ai.py` |
| The app double-checks the signed-in user | App Service sign-in adds headers naming the user (`X-MS-CLIENT-PRINCIPAL-ID` / `-NAME`), and App Service won't let a browser set them itself. The app refuses requests with no user (401) and users not in `ALLOWED_USERS` (403); an empty list lets nobody in | `app/security.py` |
| CSRF protection | Every write to `/api` must carry `X-Wealth-Portal: 1`. Browsers won't let another site add a custom header, so only the dashboard can make changes | `app/security.py`, `static/app.js` |
| Plaid tokens encrypted at rest | Fernet encryption (`cryptography` package) with `TOKEN_ENCRYPTION_KEY`, stored as `enc:v1:...`; older plaintext tokens are encrypted at startup; on Azure the app refuses to store a token without the key | `app/crypto.py`, `app/plaid_sync.py` |

Also:
- The sidebar shows "Signed in as ... · Sign out" when hosted.
- If your sign-in expires, the dashboard sends you back through Entra ID sign-in.
- 16 automated tests cover all four changes (`tests/test_security.py`; run with `python -m pytest`).

What you'll set later (Step 8), as App Service settings backed by Key Vault:

| Setting | Value |
| --- | --- |
| `TOKEN_ENCRYPTION_KEY` | A new Fernet key (command in `.env.example`). Keep a copy somewhere safe: losing it means reconnecting every bank |
| `ALLOWED_USERS` | Your Entra ID object ID (Entra admin center → Users → you → Object ID) |

Known limit: the sign-in check trusts App Service's headers, so App Service Authentication must stay on. The Bicep template (Step 5) turns it on and requires it. A possible later hardening is to also verify the signed ID token the app receives.

### Step 3: Azure Foundry lab (In progress)

You do this one hands-on: [docs/labs/step-3-azure-foundry.md](labs/step-3-azure-foundry.md).

| Part | What you do | Checkpoint (tell Claude) |
| --- | --- | --- |
| A | Portal: resource group `rg-wealth-portal`, Foundry resource, Claude deployment, budget alert | Resource name, deployment name, region (never the key) |
| B | Call Claude from a short Python script with `AnthropicFoundry` | The script's output |
| C | Wire Foundry into the app: provider setting, client factory, fixed tool loop, offline tests | Push your commit; Claude reviews it |

While preparing the lab, Claude found a bug in the current `app/ai.py`: the tool loop drops Claude's `thinking` blocks when it sends a turn back, which current models need returned unchanged, and its 1,500-token limit can cut answers off. Part C fixes both. The guide's code was run against a copy of the repo (19 tests pass); the real `app/ai.py` is left for you to change.

### Steps 4 to 12

Each step gets its own section here, with the exact commands or portal clicks, when it starts.

## Later: if the app goes public

Opening the app to other people turns a personal tool into a service that holds strangers' bank data, so it needs a separate design pass.

- **Database:** move from SQLite to Azure SQL or Azure Database for PostgreSQL.
- **Per-user data:** every account, transaction, goal and statement tied to a user, and every query (including the AI's) limited to that user.
- **Sign-in:** open Entra ID to outside accounts (for example, Entra External ID).
- **Plaid:** move from the Trial plan to a paid plan, and complete Plaid's production review.
- **Security review:** a full review, plus monitoring and alerting, before anyone else's data goes in.

## Open questions

- [ ] Azure region for the resources (pick one close to you, for example East US 2).
- [ ] Store uploaded PDF statements under `/home/data` (default) or move them to Azure Blob Storage later?
- [x] Foundry sign-in: API key in Key Vault first; keyless managed identity as a stretch goal after Step 8 (the SDK supports it through `azure_ad_token_provider`).

## Change log

| Date | What changed |
| --- | --- |
| 2026-11-12 | Plan added to the repo |
| 2026-11-12 | Production plan, tracker and decisions added; Step 1 (production config) done |
| 2026-11-12 | Step 2 (security code) done: AI token block, sign-in allow-list, CSRF check, token encryption, 16 tests |
| 2026-11-12 | Step 3 turned into a hands-on lab; lab guide added |
