# Lab: Plug Claude on Azure Foundry into Wealth Portal (plan step 3)

You set up Azure Foundry yourself, call Claude from Python, then wire it into the app's "Ask AI" page.
Claude (the coding assistant) gives you the code and reviews your work at each checkpoint.

**Time:** about 1 to 2 hours. **Cost:** a few cents of model usage, billed through the Microsoft Marketplace at Anthropic's standard API rates.

**What you'll learn**
- What a Foundry resource and a model deployment are, and how they map to an endpoint and a key
- Calling Claude from Python with the Anthropic SDK's Foundry client (`AnthropicFoundry`)
- How the app's AI "tool loop" works: Claude asks to run a query, the app runs it, Claude answers
- Keeping keys out of code and out of Git
- Testing AI code without the network or a real key (a fake HTTP server)

**Ground rules for keys**
- Never paste a key into a chat, a commit, a screenshot or a file other than `.env`. `.env` is git-ignored.
- If a key ever leaks, regenerate it in the portal. Foundry gives you two keys so you can rotate one while the other keeps working.

---

## Part A: Set up Foundry in the Azure portal

Portal labels change from time to time. If a screen doesn't match these steps, tell Claude what you see.

1. **Create a resource group.** In https://portal.azure.com, search for **Resource groups**, then **Create**.
   - Name: `rg-wealth-portal`.
   - Region: the one you picked for the plan (for example East US 2).
   - Everything for this project goes in this group, including the Bicep deployment in Step 8. Deleting the group deletes all of it.
2. **Create a Foundry resource.** Search for **Azure AI Foundry** (also shown as **Microsoft Foundry**), then create a Foundry resource in `rg-wealth-portal`.
   - Pick a globally unique name, for example `wealthportal-ai-<your initials>`.
   - Write the name down: it becomes the address `https://<name>.services.ai.azure.com`, and it's the value of `ANTHROPIC_FOUNDRY_RESOURCE` later.
   - Claude models are offered in some regions only. If the model catalog in step 3 doesn't show Claude for your region, recreate the Foundry resource in a region that does. The web app can still live in a different region.
3. **Deploy a Claude model.** Open the resource in the Foundry portal (https://ai.azure.com), go to the **Model catalog**, and search for **Claude**.
   - Pick a model. The app is set to **Claude Sonnet 5.5** today ($2 / $10 per million input / output tokens). **Claude Opus 5.5** is more capable, at $4 / $20.
   - Click **Deploy** and accept the Marketplace terms.
   - **Deployment name:** use the model ID, `claude-sonnet-5-5` (or `claude-opus-5-5`). The app sends this name as the model, so matching names mean `AI_MODEL` stays the same everywhere.
4. **Find the endpoint and key.** On the deployment's page, find the endpoint and the key.
   - The endpoint should look like `https://<name>.services.ai.azure.com/anthropic/...`.
   - Copy the key straight into `.env` in Part B; don't paste it anywhere else.
5. **Set a budget alert (good habit).** In **Cost Management → Budgets**, create a monthly budget on `rg-wealth-portal` (for example $20) with an email alert at 80%.

**Checkpoint A:** tell Claude these three things, never the key:
- your resource name,
- your deployment name,
- your region.

---

## Part B: Say hello to Claude from Python

Do this on your own computer, in VS Code's terminal. This cloud session's network can't reach Foundry, and the hands-on part is the point.

1. **Get the code.**
   ```bash
   git clone https://github.com/asareware/wealth-management.git
   cd wealth-management
   git checkout claude/gifted-bell-1ybd0p
   python3 -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
   cp .env.example .env               # Windows: copy .env.example .env
   ```
2. **Add your Foundry settings to `.env`.**
   ```
   AI_PROVIDER=foundry
   ANTHROPIC_FOUNDRY_RESOURCE=<your resource name, without https:// or .services.ai.azure.com>
   ANTHROPIC_FOUNDRY_API_KEY=<your key>
   AI_MODEL=claude-sonnet-5-5
   ```
3. **Write the script.** Create `labs/foundry_hello.py` with this code. Read the comments as you type.
   ```python
   """Lab step 3, Part B: say hello to Claude in your own Azure Foundry resource.

   Run from the repo folder:   python -m labs.foundry_hello
   It reads ANTHROPIC_FOUNDRY_RESOURCE, ANTHROPIC_FOUNDRY_API_KEY and AI_MODEL from your .env file.
   """
   import os

   from anthropic import AnthropicFoundry, APIStatusError, APIConnectionError

   from app import config  # importing config loads .env into the environment (os.environ)

   if not (os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE") and os.environ.get("ANTHROPIC_FOUNDRY_API_KEY")):
       raise SystemExit("Set ANTHROPIC_FOUNDRY_RESOURCE and ANTHROPIC_FOUNDRY_API_KEY in .env first.")

   # With no arguments, AnthropicFoundry reads ANTHROPIC_FOUNDRY_RESOURCE and ANTHROPIC_FOUNDRY_API_KEY
   # from the environment by itself.
   client = AnthropicFoundry()
   print("Calling", client.base_url, "deployment:", config.AI_MODEL)

   try:
       resp = client.messages.create(
           model=config.AI_MODEL,  # on Foundry this is your deployment name
           max_tokens=2000,
           messages=[{"role": "user", "content": "In one sentence, what is net worth?"}],
       )
   except APIStatusError as e:  # Foundry answered with an error (wrong key, wrong deployment name, quota...)
       raise SystemExit(f"Foundry returned {e.status_code}: {e.message}")
   except APIConnectionError:
       raise SystemExit("Couldn't reach Foundry. Check the resource name and your internet connection.")

   for block in resp.content:
       if block.type == "text":
           print("\nClaude:", block.text)
   print(f"\nstop_reason={resp.stop_reason}  input_tokens={resp.usage.input_tokens}  output_tokens={resp.usage.output_tokens}")
   ```
4. **Run it.**
   ```bash
   python -m labs.foundry_hello
   ```
   You should see Claude's one-sentence answer and the token counts.

**What just happened**
- `AnthropicFoundry` is the same client as Anthropic's regular one, pointed at `https://<resource>.services.ai.azure.com/anthropic/` and sending your Foundry key in the `x-api-key` header.
- `model=` is your **deployment name**, not a catalog name. That's why the deployment name matches the model ID.
- `stop_reason` tells you why Claude stopped: `end_turn` means it finished. The app also handles `tool_use`, `max_tokens` and `refusal`.

**If it fails**

| Error | Usual cause |
| --- | --- |
| 401 | Wrong key, or a stray space or quote around it in `.env` |
| 404 | The deployment name in `AI_MODEL` doesn't match the portal, or the resource name is wrong |
| 429 | Rate limit or quota on the deployment; wait a minute, or raise the quota in the portal |
| Couldn't reach Foundry | The resource name has a typo, or you included `https://` in it |

**Checkpoint B:** paste the script's output to Claude (it contains no secrets).

---

## Part C: Wire Foundry into the app

Four small edits. Make them yourself; each one comes with the reason.

### 1. `app/config.py`: choose the provider

Replace these two lines:
```python
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-5-5")
```
with:
```python
# AI assistant. AI_PROVIDER picks where the app reaches Claude:
#   "anthropic": Anthropic's API directly, using ANTHROPIC_API_KEY
#   "foundry":   Claude deployed in your Azure Foundry resource
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").strip().lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_FOUNDRY_RESOURCE = os.getenv("ANTHROPIC_FOUNDRY_RESOURCE", "")  # e.g. "wealthportal-ai"
ANTHROPIC_FOUNDRY_API_KEY = os.getenv("ANTHROPIC_FOUNDRY_API_KEY", "")
# On Anthropic: a model ID. On Foundry: your deployment's name (keep it the same as the model ID).
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-5-5")
```
**Why:** one setting switches providers. Local runs can keep using Anthropic directly, and production uses Foundry, with no code change between them.

### 2. `app/ai.py`: a client factory and a fixed tool loop

Replace the whole `chat()` function at the bottom of `app/ai.py` with:
```python
def configured() -> bool:
    """Is the chosen AI provider set up?"""
    if config.AI_PROVIDER == "foundry":
        return bool(config.ANTHROPIC_FOUNDRY_RESOURCE and config.ANTHROPIC_FOUNDRY_API_KEY)
    return bool(config.ANTHROPIC_API_KEY)


def _client():
    """Build the API client for the chosen provider. Both expose the same messages.create()."""
    import anthropic
    if config.AI_PROVIDER == "foundry":
        # Sends requests to https://<resource>.services.ai.azure.com/anthropic/
        return anthropic.AnthropicFoundry(resource=config.ANTHROPIC_FOUNDRY_RESOURCE,
                                          api_key=config.ANTHROPIC_FOUNDRY_API_KEY)
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def chat(messages: list[dict]) -> dict:
    """messages: [{role: 'user'|'assistant', content: str}, ...] -> {reply, steps}"""
    if not configured():
        need = ("ANTHROPIC_FOUNDRY_RESOURCE and ANTHROPIC_FOUNDRY_API_KEY" if config.AI_PROVIDER == "foundry"
                else "ANTHROPIC_API_KEY")
        return {"reply": f"The AI assistant isn't set up yet: add {need} to the settings and restart.", "steps": []}
    client = _client()
    convo = [{"role": m["role"], "content": m["content"]} for m in messages[-20:]]
    steps = []
    system = _system_prompt()
    for _ in range(8):  # tool-use loop
        resp = client.messages.create(model=config.AI_MODEL, max_tokens=16000, system=system,
                                      tools=TOOLS, messages=convo)
        if resp.stop_reason == "refusal":
            return {"reply": "The AI declined to answer that. Try rephrasing the question.", "steps": steps}
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if resp.stop_reason == "max_tokens":
                text += "\n\n(The answer was cut off. Try a narrower question.)"
            return {"reply": text or "(no answer)", "steps": steps}
        # Send Claude's whole turn back unchanged, including any thinking blocks:
        # the API expects them back exactly as it sent them.
        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                out = _call_tool(b.name, b.input)
                steps.append({"tool": b.name, "input": b.input})
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, default=str)[:30000]})
        convo.append({"role": "user", "content": results})
    return {"reply": "That question took too many steps. Try asking it more specifically.", "steps": steps}
```
**Why, line by line**
- `_client()` is the only place that knows about providers. Everything after it is identical for Anthropic and Foundry.
- **The bug this fixes:** the old loop rebuilt Claude's turn keeping only `text` and `tool_use` blocks. Current Claude models think before they answer, and their turns include `thinking` blocks that must go back exactly as received, so the old loop dropped something the API needs. Sending `resp.content` back unchanged is the documented pattern.
- `max_tokens` goes from 1,500 to 16,000. Thinking counts toward this limit, so 1,500 could cut answers off mid-sentence.
- `refusal` and `max_tokens` stop reasons now give a clear message instead of an empty or partial answer.

### 3. `app/main.py`: report the provider on the status page

In `status()`, replace:
```python
"ai_configured": bool(config.ANTHROPIC_API_KEY), "ai_model": config.AI_MODEL,
```
with:
```python
"ai_configured": ai.configured(), "ai_provider": config.AI_PROVIDER, "ai_model": config.AI_MODEL,
```

### 4. `tests/test_ai_foundry.py`: test it without the network

Create this file. It runs the real tool loop against a **fake Foundry server**: `httpx2.MockTransport` answers the HTTP requests the SDK sends, so no key or network is needed. That makes it safe to run in CI, which comes in Step 4.
```python
"""Lab step 3: the Foundry client and the tool loop, tested against a fake Foundry server.

No network and no real key: httpx2.MockTransport answers the requests the SDK would send."""
import json

import httpx2
from anthropic import AnthropicFoundry

from app import ai, config


def test_foundry_is_chosen_and_points_at_your_resource(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "foundry")
    monkeypatch.setattr(config, "ANTHROPIC_FOUNDRY_RESOURCE", "my-resource")
    monkeypatch.setattr(config, "ANTHROPIC_FOUNDRY_API_KEY", "not-a-real-key")
    assert ai.configured()
    client = ai._client()
    assert isinstance(client, AnthropicFoundry)
    assert str(client.base_url) == "https://my-resource.services.ai.azure.com/anthropic/"


def test_foundry_without_key_is_not_configured(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "foundry")
    monkeypatch.setattr(config, "ANTHROPIC_FOUNDRY_API_KEY", "")
    assert not ai.configured()
    assert "ANTHROPIC_FOUNDRY_API_KEY" in ai.chat([{"role": "user", "content": "hi"}])["reply"]


def _message(content, stop_reason):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}


def test_tool_loop_runs_a_tool_and_sends_thinking_back(client, monkeypatch):
    sent = []  # every request body the app sends to "Foundry"

    def fake_foundry(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        sent.append(body)
        assert request.headers["x-api-key"] == "not-a-real-key"
        if len(sent) == 1:  # first turn: Claude thinks, then asks for a tool
            return httpx2.Response(200, json=_message([
                {"type": "thinking", "thinking": "", "signature": "sig-123"},
                {"type": "tool_use", "id": "tu_1", "name": "get_summary", "input": {"period": "today"}},
            ], "tool_use"))
        return httpx2.Response(200, json=_message([{"type": "text", "text": "You spent $0.00 today."}], "end_turn"))

    monkeypatch.setattr(config, "AI_PROVIDER", "foundry")
    monkeypatch.setattr(config, "ANTHROPIC_FOUNDRY_RESOURCE", "my-resource")
    monkeypatch.setattr(config, "ANTHROPIC_FOUNDRY_API_KEY", "not-a-real-key")
    monkeypatch.setattr(ai, "_client", lambda: AnthropicFoundry(
        resource="my-resource", api_key="not-a-real-key",
        http_client=httpx2.Client(transport=httpx2.MockTransport(fake_foundry))))

    out = ai.chat([{"role": "user", "content": "How much did I spend today?"}])

    assert out["reply"] == "You spent $0.00 today."
    assert out["steps"] == [{"tool": "get_summary", "input": {"period": "today"}}]
    second = sent[1]["messages"]
    assistant_turn = second[1]["content"]
    assert assistant_turn[0]["type"] == "thinking" and assistant_turn[0]["signature"] == "sig-123"
    assert second[2]["content"][0]["type"] == "tool_result" and second[2]["content"][0]["tool_use_id"] == "tu_1"
```
Run all the tests:
```bash
python -m pytest -q
```
Expect **19 passed**. To see the fake server catch the old bug, temporarily put the old block-rebuilding loop back: the last test fails.

### 5. Try it for real

```bash
python run.py
```
- In **Connect & settings**, click **Load demo data**. The AI assistant line should no longer say "Off".
- Ask AI: "How much did I spend today?", "What were my top 3 merchants last month?", "How far am I from my net worth goal?"
- Under each answer, the app lists the tools Claude used: that's the tool loop at work.

**Checkpoint C:** commit and push, then tell Claude to review your push.
```bash
git add -A
git commit -m "Use Claude on Azure Foundry for Ask AI (plan step 3)"
git push
```

---

## Stretch goal (after Step 8): no key at all

The Foundry client can also sign in with an Azure identity instead of a key (`azure_ad_token_provider=`). Once the web app exists:
- Give its managed identity a role on the Foundry resource.
- Use `azure-identity` to get tokens.
- Delete the key from Key Vault.

Claude will walk you through it and check the exact role and token scope in the Foundry docs at that point.
