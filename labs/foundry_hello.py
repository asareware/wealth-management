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
