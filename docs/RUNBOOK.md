# RUNBOOK — set up, run, connect

Step-by-step to go from a clone to "Claude can read and write my memory."

## 0. Prerequisites

- Python 3.10+.
- **Ollama** (optional but recommended for quality): install from
  <https://ollama.com>, then:
  ```bash
  ollama pull nomic-embed-text     # embeddings (the quality backend)
  ollama pull qwen2.5:3b           # optional: local answer-synthesis / extraction
  ```
  No Ollama? Use `PMEM_EMBED_BACKEND=hash` everywhere below and skip the pulls.
- **ngrok** (or any HTTPS tunnel) to expose the local server to Claude.ai.

## 1. Install

```bash
cd personal-graphrag
python -m venv venv
. venv/bin/activate                 # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Choose a backend (per graph — pick one and stick with it)

```bash
# Quality (default): local embeddings via Ollama
export PMEM_EMBED_BACKEND=ollama    # Windows PS: $env:PMEM_EMBED_BACKEND="ollama"

# OR zero-dependency, no service (lower quality; great for trying it out / CI)
export PMEM_EMBED_BACKEND=hash
```

Switching later means a one-time `python rebuild.py` (vectors aren't comparable
across backends).

## 3. Build the graph

```bash
python seed_memory.py        # plants grounded starter memories -> journal + graph
# ...or start empty and add your own:
python add_memory.py --name "My First Note" --type note --category ideas --desc "hello"
```

Verify:

```bash
python memory_health.py      # expect: nodes>0, UNKNOWN-typed 0, isolated 0
python recall.py "what's in my memory?"
```

## 4. Serve to Claude.ai

```bash
python mcp_server.py         # serves Streamable HTTP on 0.0.0.0:8000 at path "/"
```

In another terminal:

```bash
ngrok http 8000
```

Then in Claude.ai → **Settings → Connectors → Add custom connector**:

- **URL:** the bare ngrok HTTPS URL (e.g. `https://abc123.ngrok-free.app`) — **no
  `/mcp`, no `/sse`, no trailing path.**
- **OAuth:** leave blank.

You should see the 10 tools. Ask Claude to "remember that I'm using Godot for my
game" and then "what am I building?" — it should call `remember` then
`search_memory`.

### Connection gotchas (inherited from the MSP PoC)

- **Root path.** The server mounts at `/` on purpose. FastMCP's default `/mcp`
  makes Claude.ai 404 and then show a misleading OAuth/sign-in error. Don't change it.
- **Manifest cache.** After changing tools, restart the server **and** toggle the
  connector off/on in Claude.ai, or the old tool list sticks.
- **Restart after a rebuild.** A running server holds the graph in memory. After
  `rebuild.py` (or any big offline change), restart `mcp_server.py`.

## 5. Day-to-day

```bash
# add via CLI (when not in a Claude session)
echo '{"entities":[{"name":"Sam","type":"person","category":"social"}],
       "relationships":[{"source":"Devon","target":"Sam","relation":"knows"}]}' \
  | python add_memory.py --json -

# query
python recall.py "who do I know?"               # no-LLM
python recall.py "summarize my projects" --llm  # local-model prose (needs Ollama)

# optional: ingest a text file via the local model (review-only by default)
python extract_local.py --file ~/notes/2026-06-09.md
python extract_local.py --file ~/notes/2026-06-09.md --commit

# maintenance
python memory_health.py                         # offline health
python rebuild.py --dry-run                      # preview a rebuild
python rebuild.py                                # rebuild graph/ from the journal
```

## 6. Backups

The only thing you must back up is **`data/memory_journal.jsonl`** — it's the
source of truth, plain JSONL, and `rebuild.py` reconstructs everything else from
it. (It's `.gitignore`d by default for privacy; version it deliberately once your
memory matters to you.)

## Troubleshooting

| Symptom | Fix |
|---|---|
| Claude.ai shows OAuth/sign-in error on connect | URL has a path or `/mcp`; use the bare HTTPS root. |
| Tools don't update after a change | Restart server **and** toggle the connector. |
| `recall`/`extract_local` say Ollama unreachable | `ollama serve` + pull the models, or use `search_memory`. |
| Retrieval feels weak | You're probably on `hash`; switch to `ollama` and `rebuild.py`. |
| Graph looks wrong / half-built | `python rebuild.py` (journal is authoritative). |
| Slow first query | Ollama cold-loads the model; first call pays ~setup cost. |
