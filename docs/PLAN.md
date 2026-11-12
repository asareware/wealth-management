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
| 2 | Security code: AI can't read Plaid tokens; app double-checks the signed-in user; writes need a same-site header (CSRF); Plaid tokens encrypted at rest | Claude (code) | Next |
| 3 | Azure Foundry option in `app/ai.py` | Claude (code) | Not started |
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

### Step 2: Security code (Next)

| Change | Why | Breaks anything? |
| --- | --- | --- |
| Block the AI from reading `access_token` and `cursor` | A query like `SELECT * FROM institutions` would send Plaid tokens to the AI service | No; no money question needs those columns |
| App checks the signed-in user from App Service Authentication against an allow-list | A second lock: even if sign-in were misconfigured, the app refuses anyone else | No; local runs skip it |
| Write requests must carry a header only the app's own pages send | Stops another website from submitting actions using your signed-in session (CSRF) | No; the dashboard sends it |
| Encrypt Plaid tokens in the database | A copied database file would otherwise expose working bank tokens | No; existing tokens are encrypted on first start |

### Steps 3 to 12

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
- [ ] Foundry: API key in Key Vault (default), or the web app's managed identity?

## Change log

| Date | What changed |
| --- | --- |
| 2026-11-12 | Plan added to the repo |
| 2026-11-12 | Production plan, tracker and decisions added; Step 1 (production config) done |
