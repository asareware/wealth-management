const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const money = v => (v ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtDate = Charts.fmtDate;

async function api(path, opts = {}) {
  const o = { ...opts };
  // X-Wealth-Portal: the CSRF check (other sites can't add this header; see app/security.py).
  // X-Requested-With: tells App Service sign-in to answer 401 instead of redirecting a background request.
  o.headers = { "X-Wealth-Portal": "1", "X-Requested-With": "XMLHttpRequest", ...(o.headers || {}) };
  if (o.body && !(o.body instanceof FormData)) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(o.body); }
  const r = await fetch(path, o);
  if (r.status === 401) { // sign-in expired: go to App Service's Entra ID sign-in, then come back here
    location.href = "/.auth/login/aad?post_login_redirect_uri=" + encodeURIComponent(location.pathname);
    return new Promise(() => {});
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

let STATUS = {}, PERIOD = "month", ACCOUNTS = [];

// ---------- navigation ----------
function show(view) {
  $$("nav button").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $$("main > section").forEach(s => s.classList.toggle("hidden", s.id !== "view-" + view));
  ({ overview: loadOverview, transactions: () => loadTx(true), statements: loadStatements, goals: loadGoals,
     accounts: loadAccounts, settings: loadSettings, ask: () => $("#chatIn").focus() })[view]?.();
  history.replaceState(null, "", "#" + view);
}
$$("nav button").forEach(b => b.onclick = () => show(b.dataset.view));
document.addEventListener("click", e => { const g = e.target.closest("[data-goto]"); if (g) { e.preventDefault(); show(g.dataset.goto); } });

async function refreshStatus() {
  STATUS = await api("/api/status");
  $("#brandNote").innerHTML = STATUS.user
    ? `Signed in as ${esc(STATUS.user)} · <a href="/.auth/logout">Sign out</a>`
    : STATUS.hosted ? "Private" : "Private · runs on this computer";
  $("#demoBanner").classList.toggle("hidden", !STATUS.demo);
  ACCOUNTS = await api("/api/accounts");
  const last = ACCOUNTS.map(a => a.last_synced).filter(Boolean).sort().at(-1);
  $("#syncInfo").textContent = last ? "Last synced " + new Date(last.replace(" ", "T") + "Z").toLocaleString() : "Not synced yet";
}

// ---------- overview ----------
$$("#periodSeg button").forEach(b => b.onclick = () => {
  $$("#periodSeg button").forEach(x => x.classList.toggle("on", x === b)); PERIOD = b.dataset.p; loadOverview();
});
const PERIOD_LABEL = { today: "today", week: "this week", month: "this month", last_month: "last month", ytd: "this year" };

async function loadOverview() {
  const o = await api("/api/overview?period=" + PERIOD);
  const nw = o.net_worth, cf = o.cash_flow;
  $("#ovRange").textContent = `${fmtDate(o.start)} – ${fmtDate(o.end)}`;
  const first = o.net_worth_history[0], m30 = o.net_worth_history.findLast?.(h => h.date <= daysAgo(30));
  const chg = m30 ? nw.net_worth - m30.net_worth : null;
  $("#tiles").innerHTML = [
    tile("Net worth", money(nw.net_worth), chg == null ? `${money(nw.assets)} assets · ${money(nw.liabilities)} owed`
      : `<span class="${chg >= 0 ? "pos" : "neg"}">${chg >= 0 ? "▲" : "▼"} ${money(Math.abs(chg))}</span> vs. 30 days ago`),
    tile("Money in " + PERIOD_LABEL[PERIOD], money(cf.income), "Paychecks, interest & other income"),
    tile("Spent " + PERIOD_LABEL[PERIOD], money(cf.spending), `${cf.purchases} purchases · today ${money(o.today.spending)}`),
    tile("Saved " + PERIOD_LABEL[PERIOD], `<span class="${cf.net >= 0 ? "pos" : "neg"}">${money(cf.net)}</span>`,
      cf.savings_rate != null ? `${cf.savings_rate}% of income` : "Income minus spending"),
  ].join("");
  Charts.line($("#nwChart"), o.net_worth_history.map(h => ({ date: h.date, value: h.net_worth })));
  const firstActive = o.monthly.findIndex(m => m.income || m.spending);
  o.monthly = o.monthly.slice(Math.max(firstActive, 0));
  Charts.bars($("#cfChart"), o.monthly.map(m => m.month), [
    { name: "Income", color: "var(--s1)", values: o.monthly.map(m => m.income) },
    { name: "Spending", color: "var(--s2)", values: o.monthly.map(m => m.spending) }],
    { label: m => fmtDate(m, true), title: m => fmtDate(m) });
  Charts.bars($("#dayChart"), o.daily_spending.map(d => d.date), [{ name: "Spending", color: "var(--s1)", values: o.daily_spending.map(d => d.spending) }],
    { label: d => fmtDate(d, true), title: d => fmtDate(d), maxLabels: 6, height: 200 });
  $("#catRange").textContent = PERIOD_LABEL[PERIOD];
  const maxCat = Math.max(...o.spending_by_category.map(c => c.total), 1);
  $("#catList").innerHTML = o.spending_by_category.length ? o.spending_by_category.slice(0, 10).map(c => `
    <div class="catrow"><span>${esc(c.category)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${c.total / maxCat * 100}%"></div></div>
      <span class="num" style="text-align:right">${money(c.total)}</span></div>`).join("") : `<p class="muted">No spending ${PERIOD_LABEL[PERIOD]}.</p>`;
  $("#merchTable").innerHTML = o.top_merchants.map(m => `<tr><td>${esc(m.merchant)}</td><td class="muted small">${m.count}×</td><td class="num">${money(m.total)}</td></tr>`).join("")
    || `<tr><td class="muted">Nothing yet.</td></tr>`;
  $("#ovGoals").innerHTML = o.goals.length ? o.goals.map(goalMini).join("") : `<p class="muted">No goals yet. <a href="#" data-goto="goals">Add one</a>.</p>`;
}
const tile = (l, v, n) => `<div class="card tile"><div class="label">${l}</div><div class="value">${v}</div><div class="note">${n}</div></div>`;
const daysAgo = n => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const goalMini = g => `<div style="margin-bottom:14px"><div class="row small"><b>${esc(g.name)}</b><span class="spacer"></span>${g.percent}%</div>
  <div class="bar-track" style="margin:5px 0"><div class="bar-fill" style="width:${g.percent}%"></div></div>
  <div class="small muted">${money(g.current)} of ${money(g.target_amount)} · ${money(g.remaining)} to go</div></div>`;

// ---------- transactions ----------
let txOffset = 0, txTimer;
async function loadTx(reset) {
  if (reset) {
    txOffset = 0;
    if ($("#txAcc").options.length <= 1) ACCOUNTS.forEach(a => $("#txAcc").add(new Option(`${a.institution} · ${a.name}`, a.id)));
    const cats = await api("/api/categories");
    const cur = $("#txCat").value; $("#txCat").length = 1; cats.forEach(c => $("#txCat").add(new Option(c, c))); $("#txCat").value = cur;
  }
  const p = new URLSearchParams({ q: $("#txQ").value, account: $("#txAcc").value, kind: $("#txKind").value, category: $("#txCat").value,
    start: $("#txStart").value, end: $("#txEnd").value, limit: 100, offset: txOffset });
  const d = await api("/api/transactions?" + p);
  $("#txExport").href = `/api/transactions.csv?start=${$("#txStart").value}&end=${$("#txEnd").value}`;
  $("#txSummary").innerHTML = `<span>${d.total} transactions</span><span class="pos">In ${money(d.inflow)}</span><span class="neg">Out ${money(d.outflow)}</span>`;
  const html = d.rows.map(t => `<tr>
    <td style="white-space:nowrap">${fmtDate(t.date, true)}</td>
    <td>${esc(t.merchant || t.name)}${t.merchant && t.name !== t.merchant ? `<div class="small muted">${esc(t.name)}</div>` : ""}${t.pending ? ' <span class="pill">pending</span>' : ""}</td>
    <td class="small">${esc(t.institution)}<div class="muted">${esc(t.account)}</div></td>
    <td><span class="pill" style="cursor:pointer" data-edit="${t.id}" title="Click to change">${esc(t.category || "—")}</span></td>
    <td class="small muted">${t.kind}</td>
    <td class="num ${t.amount > 0 ? "pos" : ""}">${t.amount > 0 ? "+" : ""}${money(t.amount)}</td></tr>`).join("");
  $("#txBody").innerHTML = reset ? html : $("#txBody").innerHTML + html;
  $("#txMore").classList.toggle("hidden", txOffset + 100 >= d.total);
}
["#txQ"].forEach(s => $(s).oninput = () => { clearTimeout(txTimer); txTimer = setTimeout(() => loadTx(true), 250); });
["#txAcc", "#txKind", "#txCat", "#txStart", "#txEnd"].forEach(s => $(s).onchange = () => loadTx(true));
$("#txMore").onclick = () => { txOffset += 100; loadTx(false); };
$("#txBody").onclick = async e => {
  const p = e.target.closest("[data-edit]"); if (!p) return;
  const cat = prompt("New category for this transaction:", p.textContent); if (cat == null) return;
  const kind = prompt("Type: spending, income or transfer", "spending"); if (!["spending", "income", "transfer"].includes(kind)) return;
  await api("/api/transactions/" + p.dataset.edit, { method: "PATCH", body: { category: cat, kind } });
  loadTx(true);
};

// ---------- statements ----------
function prevMonth() { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 7); }
async function loadStatements() {
  if (!$("#stMonth").value) $("#stMonth").value = prevMonth();
  const s = await api("/api/statement?month=" + $("#stMonth").value);
  const c = s.summary;
  $("#stBody").innerHTML = `
    <p class="small muted">${fmtDate(s.start)} – ${fmtDate(s.end)} · all connected accounts</p>
    <div class="grid g4">${tile("Opening net worth", s.opening_net_worth == null ? "—" : money(s.opening_net_worth), "")}
      ${tile("Money in", money(c.income), "")}${tile("Money out (spending)", money(c.spending), c.savings_rate != null ? `Saved ${c.savings_rate}% of income` : "")}
      ${tile("Closing net worth", s.closing_net_worth == null ? "—" : money(s.closing_net_worth),
        s.opening_net_worth != null && s.closing_net_worth != null ? `Change ${money(s.closing_net_worth - s.opening_net_worth)}` : "")}</div>
    <div class="grid g2" style="margin-top:16px">
      <div><h2>Income</h2><table>${s.income_sources.map(i => `<tr><td>${esc(i.source)}</td><td class="muted small">${i.count}×</td><td class="num">${money(i.total)}</td></tr>`).join("") || "<tr><td class='muted'>None</td></tr>"}</table>
        <h2 style="margin-top:16px">By account</h2><table><tr><th>Account</th><th class="num">In</th><th class="num">Out</th></tr>
        ${s.accounts.map(a => `<tr><td>${esc(a.institution)} · ${esc(a.name)}</td><td class="num">${money(a.money_in)}</td><td class="num">${money(a.money_out)}</td></tr>`).join("")}</table></div>
      <div><h2>Spending by category</h2><table>${s.spending_by_category.map(x => `<tr><td>${esc(x.category)}</td><td class="muted small">${x.count}×</td><td class="num">${money(x.total)}</td></tr>`).join("") || "<tr><td class='muted'>None</td></tr>"}</table></div>
    </div>
    <h2 style="margin-top:16px">All transactions (${s.transactions.length})</h2>
    <table><tr><th>Date</th><th>Description</th><th>Account</th><th>Category</th><th class="num">Amount</th></tr>
    ${s.transactions.map(t => `<tr><td>${fmtDate(t.date, true)}</td><td>${esc(t.description)}</td><td class="small">${esc(t.account)}</td><td class="small">${esc(t.category)}${t.kind === "transfer" ? " (transfer)" : ""}</td><td class="num ${t.amount > 0 ? "pos" : ""}">${money(t.amount)}</td></tr>`).join("")}</table>`;
  const files = await api("/api/statement-files");
  $("#stFiles").innerHTML = files.map(f => `<tr><td><a href="/api/statement-files/${f.id}/pdf" target="_blank">${esc(f.filename)}</a></td>
    <td>${esc(f.institution)}</td><td>${esc(f.period)}</td><td class="num">${f.pages}</td>
    <td class="num"><button class="btn danger small" data-del-st="${f.id}">Delete</button></td></tr>`).join("")
    || `<tr><td class="muted" colspan="5">No PDFs uploaded yet. Download statements from each bank's website and upload them here to search inside them.</td></tr>`;
}
$("#stMonth").onchange = loadStatements;
$("#upFile").onchange = async e => {
  for (const f of e.target.files) {
    const fd = new FormData(); fd.append("file", f); fd.append("institution", $("#upInst").value); fd.append("period", $("#upPeriod").value);
    try { const r = await api("/api/statement-files", { method: "POST", body: fd });
      if (r.pages_without_text === r.pages) alert(`${f.name}: this looks like a scanned PDF with no text, so it can't be searched.`);
    } catch (err) { alert(err.message); }
  }
  e.target.value = ""; loadStatements();
};
$("#stFiles").onclick = async e => { const b = e.target.closest("[data-del-st]"); if (b && confirm("Delete this statement?")) { await api("/api/statement-files/" + b.dataset.delSt, { method: "DELETE" }); loadStatements(); } };
let stTimer;
$("#stQ").oninput = () => { clearTimeout(stTimer); stTimer = setTimeout(async () => {
  const q = $("#stQ").value.trim(); if (!q) { $("#stSearch").innerHTML = ""; return; }
  const r = await api("/api/statement-search?q=" + encodeURIComponent(q));
  // snippet is built server-side from your own PDFs; only <mark> tags are allowed through
  const safe = s => esc(s).replace(/&lt;(\/?)mark&gt;/g, "<$1mark>");
  $("#stSearch").innerHTML = r.length ? `<table style="margin-bottom:14px">${r.map(x => `<tr><td style="width:220px"><a href="/api/statement-files/${x.id}/pdf#page=${x.page}" target="_blank">${esc(x.filename)}</a><div class="small muted">page ${x.page}</div></td><td class="small">${safe(x.snippet)}</td></tr>`).join("")}</table>`
    : `<p class="muted small">No matches.</p>`;
}, 250); };

// ---------- goals ----------
async function loadGoals() {
  const goals = await api("/api/goals");
  $("#goalCards").innerHTML = goals.length ? goals.map(g => `<div class="card">
    <div class="row"><h2 style="margin:0">${esc(g.name)}</h2><span class="spacer"></span><button class="btn danger small" data-del-goal="${g.id}">Delete</button></div>
    <div class="tile"><div class="value">${g.percent}%</div><div class="note">${money(g.current)} of ${money(g.target_amount)}</div></div>
    <div class="bar-track" style="margin:10px 0"><div class="bar-fill" style="width:${g.percent}%"></div></div>
    <table class="small">
      <tr><td>Still to go</td><td class="num"><b>${money(g.remaining)}</b></td></tr>
      ${g.target_date ? `<tr><td>Target date</td><td class="num">${fmtDate(g.target_date)} (${g.months_left} months)</td></tr>
      <tr><td>Needed per month</td><td class="num">${money(g.needed_per_month)}</td></tr>` : ""}
      <tr><td>Your current pace</td><td class="num">${money(g.current_pace_per_month)} / month</td></tr>
      <tr><td>At this pace you'll get there</td><td class="num">${g.projected_date ? fmtDate(g.projected_date) : "— (pace is zero or negative)"}</td></tr>
      ${g.on_track != null ? `<tr><td>Status</td><td class="num ${g.on_track ? "pos" : "neg"}">${g.on_track ? "✔ On track" : "✖ Behind: need " + money(g.needed_per_month - g.current_pace_per_month) + " more per month"}</td></tr>` : ""}
    </table>
    <p class="small muted">${g.metric === "net_worth" ? "Measured by total net worth. Pace = average monthly income minus spending, last 3 full months." : "Measured by the chosen accounts. Pace = how fast they grew over the last 3 months."}</p>
  </div>`).join("") : `<div class="card muted">No goals yet. Click <b>Add goal</b>.</div>`;
}
$("#goalCards").onclick = async e => { const b = e.target.closest("[data-del-goal]"); if (b && confirm("Delete goal?")) { await api("/api/goals/" + b.dataset.delGoal, { method: "DELETE" }); loadGoals(); } };
$("#addGoalBtn").onclick = () => {
  $("#goalAccList").innerHTML = ACCOUNTS.map(a => `<label style="margin:4px 0;color:var(--ink)"><input type="checkbox" value="${a.id}" style="width:auto"> ${esc(a.institution)} · ${esc(a.name)}</label>`).join("");
  $("#goalForm").reset(); $("#goalAccs").classList.add("hidden"); $("#goalDlg").showModal();
};
$("#goalForm").metric.onchange = e => $("#goalAccs").classList.toggle("hidden", e.target.value !== "accounts");
$("#goalDlg").onclose = async () => {
  if ($("#goalDlg").returnValue !== "ok") return;
  const f = $("#goalForm");
  await api("/api/goals", { method: "POST", body: { name: f.name.value, target_amount: f.target_amount.value, target_date: f.target_date.value,
    metric: f.metric.value, account_ids: $$("#goalAccList input:checked").map(i => i.value) } });
  loadGoals();
};

// ---------- accounts ----------
const TYPE_LABEL = { depository: "Cash", credit: "Credit cards", investment: "Investments", loan: "Loans", other: "Other" };
async function loadAccounts() {
  await refreshStatus();
  const groups = {};
  ACCOUNTS.forEach(a => (groups[a.type] ||= []).push(a));
  const nw = ACCOUNTS.reduce((s, a) => s + (a.is_asset ? a.current_balance : -a.current_balance), 0);
  $("#accSub").textContent = `${ACCOUNTS.length} accounts · net worth ${money(nw)}`;
  $("#accList").innerHTML = ["depository", "investment", "credit", "loan", "other"].filter(t => groups[t]).map(t => {
    const total = groups[t].reduce((s, a) => s + a.current_balance, 0);
    return `<div class="card" style="margin-bottom:16px"><div class="row"><h2 style="margin:0">${TYPE_LABEL[t]}</h2><span class="spacer"></span><b>${t === "credit" || t === "loan" ? "Owed " : ""}${money(total)}</b></div>
      <table style="margin-top:8px">${groups[t].map(a => `<tr>
        <td>${esc(a.name)} ${a.mask ? `<span class="muted small">••${esc(a.mask)}</span>` : ""}<div class="small muted">${esc(a.institution)} · ${esc(a.subtype || a.type)}${a.institution_status !== "ok" ? ` · <span class="neg">${a.institution_status === "needs_relogin" ? "needs re-login" : "sync error"}</span>` : ""}</div>
          ${a.holdings?.length ? `<div class="small" style="margin-top:4px">${a.holdings.map(h => `${esc(h.ticker || h.security)} ${money(h.value)}`).join(" · ")}</div>` : ""}</td>
        <td class="num">${money(a.current_balance)}${a.credit_limit ? `<div class="small muted">limit ${money(a.credit_limit)}</div>` : ""}</td>
        <td class="num">${a.provider === "manual" ? `<button class="btn small" data-bal="${a.id}">Update balance</button>` : ""}
          <button class="btn small" data-hide="${a.id}">Hide</button></td></tr>`).join("")}</table></div>`;
  }).join("") || `<div class="card muted">No accounts yet. Go to <a href="#" data-goto="settings">Connect &amp; settings</a>.</div>`;
}
$("#accList").onclick = async e => {
  const b = e.target.closest("[data-bal]"), h = e.target.closest("[data-hide]");
  if (b) { const v = prompt("New balance ($):"); if (v != null && !isNaN(+v)) { await api(`/api/accounts/${b.dataset.bal}/balance`, { method: "POST", body: { balance: +v } }); loadAccounts(); } }
  if (h && confirm("Hide this account from all totals? (You can't undo this from the UI yet.)")) { await api("/api/accounts/" + h.dataset.hide, { method: "PATCH", body: { hidden: 1 } }); loadAccounts(); }
};

// ---------- ask AI ----------
const convo = [];
function addMsg(role, text, steps) {
  const d = document.createElement("div"); d.className = "msg " + role; d.textContent = text;
  if (steps?.length) { const s = document.createElement("div"); s.className = "steps"; s.textContent = "Looked up: " + steps.map(x => x.tool.replace("_", " ")).join(", "); d.appendChild(s); }
  $("#msgs").appendChild(d); $("#msgs").scrollTop = 1e9; return d;
}
async function ask(q) {
  $("#suggest")?.remove();
  addMsg("user", q); convo.push({ role: "user", content: q });
  const wait = addMsg("assistant", "Checking your accounts…");
  try {
    const r = await api("/api/chat", { method: "POST", body: { messages: convo } });
    wait.remove(); addMsg("assistant", r.reply, r.steps); convo.push({ role: "assistant", content: r.reply });
  } catch (e) { wait.textContent = "Error: " + e.message; }
}
$("#chatForm").onsubmit = e => { e.preventDefault(); const q = $("#chatIn").value.trim(); if (q) { $("#chatIn").value = ""; ask(q); } };
$("#suggest").onclick = e => { if (e.target.tagName === "BUTTON") ask(e.target.textContent); };

// ---------- settings / connect ----------
async function loadSettings() {
  await refreshStatus();
  $("#plaidState").innerHTML = STATUS.plaid_configured
    ? `Plaid connected (<b>${STATUS.plaid_env}</b>). Balances and transactions refresh every 6 hours while the portal is running.`
    : `<span class="neg">Plaid keys not set.</span> Add <code>PLAID_CLIENT_ID</code> and <code>PLAID_SECRET</code> to your <code>.env</code> file and restart. See the README.`;
  ["#linkBank", "#linkInv", "#syncBtn"].forEach(s => $(s).disabled = !STATUS.plaid_configured);
  $("#aiState").innerHTML = STATUS.ai_configured ? `On (model ${esc(STATUS.ai_model)}). When you ask a question, the numbers needed to answer it are sent to Anthropic's API.`
    : `<span class="neg">Off.</span> Add <code>ANTHROPIC_API_KEY</code> to <code>.env</code> to turn it on.`;
  const inst = await api("/api/institutions");
  $("#instTable").innerHTML = inst.map(i => `<tr><td>${esc(i.name)}${i.is_demo ? ' <span class="pill">demo</span>' : ""}<div class="small muted">${i.provider}${i.last_synced ? " · synced " + new Date(i.last_synced.replace(" ", "T") + "Z").toLocaleString() : ""}</div></td>
    <td class="small ${i.status === "ok" ? "" : "neg"}">${i.status === "needs_relogin" ? "needs re-login" : i.status}</td>
    <td class="num">${i.status === "needs_relogin" ? `<button class="btn small" data-relink="${i.id}">Re-login</button>` : ""}
      ${i.is_demo ? "" : `<button class="btn small danger" data-rm="${i.id}">Disconnect</button>`}</td></tr>`).join("")
    || `<tr><td class="muted">Nothing connected yet.</td></tr>`;
  $("#csvAcc").innerHTML = ACCOUNTS.map(a => `<option value="${a.id}">${esc(a.institution)} · ${esc(a.name)}</option>`).join("") || `<option value="">Add an account first</option>`;
  const rules = await api("/api/rules");
  $("#ruleTable").innerHTML = rules.map(r => `<tr><td class="small">"${esc(r.pattern)}"</td><td class="small">→ ${esc(r.category || "")} ${r.kind ? "(" + r.kind + ")" : ""}</td><td class="num"><button class="btn small" data-rule="${r.id}">✕</button></td></tr>`).join("");
}
async function plaidLink(mode, institution_id) {
  try {
    const { link_token } = await api("/api/plaid/link-token", { method: "POST", body: { mode, institution_id } });
    Plaid.create({
      token: link_token,
      onSuccess: async public_token => {
        if (institution_id) { await api("/api/sync", { method: "POST" }); }
        else { $("#plaidState").textContent = "Linking and downloading your history… (can take a minute)";
               await api("/api/plaid/exchange", { method: "POST", body: { public_token } }); }
        loadSettings();
      },
      onExit: err => { if (err) alert("Plaid: " + (err.display_message || err.error_message || err.error_code)); },
    }).open();
  } catch (e) { alert(e.message); }
}
$("#linkBank").onclick = () => plaidLink("banking");
$("#linkInv").onclick = () => plaidLink("investments");
$("#syncBtn").onclick = async () => { $("#syncBtn").textContent = "Syncing…"; const r = await api("/api/sync", { method: "POST" }); $("#syncBtn").textContent = "Sync now";
  const bad = Object.values(r).filter(x => x && x.ok === false); if (bad.length) alert(bad.length + " connection(s) had a problem; see the list."); loadSettings(); };
$("#instTable").onclick = async e => {
  const rm = e.target.closest("[data-rm]"), rl = e.target.closest("[data-relink]");
  if (rm && confirm("Disconnect this institution and delete its accounts and transactions from the portal?")) { await api("/api/institutions/" + rm.dataset.rm, { method: "DELETE" }); loadSettings(); }
  if (rl) plaidLink("banking", rl.dataset.relink);
};
$("#addManual").onclick = () => { $("#manualForm").reset(); $("#manualDlg").showModal(); };
$("#manualDlg").onclose = async () => {
  if ($("#manualDlg").returnValue !== "ok") return;
  const f = $("#manualForm");
  await api("/api/manual-accounts", { method: "POST", body: { institution: f.institution.value, name: f.name.value, type: f.type.value, balance: f.balance.value } });
  loadSettings();
};
$("#csvFile").onchange = async e => {
  const f = e.target.files[0]; if (!f || !$("#csvAcc").value) return;
  const fd = new FormData(); fd.append("file", f); fd.append("account_id", $("#csvAcc").value); fd.append("flip_sign", $("#csvFlip").checked);
  const r = await api("/api/import-csv", { method: "POST", body: fd });
  $("#csvMsg").textContent = r.ok ? `Imported ${r.added} (${r.skipped_or_duplicate} skipped/duplicate)` : r.error; e.target.value = "";
};
$("#ruleAdd").onclick = async () => {
  if (!$("#rulePat").value.trim()) return;
  await api("/api/rules", { method: "POST", body: { pattern: $("#rulePat").value, category: $("#ruleCat").value, kind: $("#ruleKind").value } });
  $("#rulePat").value = $("#ruleCat").value = ""; loadSettings();
};
$("#ruleTable").onclick = async e => { const b = e.target.closest("[data-rule]"); if (b) { await api("/api/rules/" + b.dataset.rule, { method: "DELETE" }); loadSettings(); } };
$("#demoAdd").onclick = async () => { await api("/api/demo", { method: "POST" }); await refreshStatus(); show("overview"); };
$("#demoDel").onclick = async () => { if (confirm("Remove all demo data?")) { await api("/api/demo", { method: "DELETE" }); await refreshStatus(); loadSettings(); } };

// ---------- boot ----------
window.addEventListener("hashchange", () => { const v = location.hash.slice(1); if ($("#view-" + v)) show(v); });
let resizeT; window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => { if (!$("#view-overview").classList.contains("hidden")) loadOverview(); }, 200); });
(async () => {
  await refreshStatus();
  const start = location.hash.slice(1) || (STATUS.accounts ? "overview" : "settings");
  show($("#view-" + start) ? start : "overview");
})();
