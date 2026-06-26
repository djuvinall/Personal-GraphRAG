# CLAUDE.md

Working guide for Claude (and humans) operating in the **Personal GraphRAG** repo —
Devon's self-hosted memory graph. Read this first. It covers what the project is,
the one principle that defines it, how to *remember well*, the commands, and the
traps. Deeper detail is in [`docs/`](./docs).

---

## What this project is

A single-user **GraphRAG** for **persistent personal memory**, adapted from an
earlier MSP GraphRAG PoC I built. Same engine — **LightRAG** (hybrid vector + graph retrieval)
with **Ollama** serving embeddings locally, reached from Claude.ai through a
**FastMCP** server over an **ngrok** tunnel — but the schema models *Devon's life*
(people, projects, ideas, tools, tasks, notes, preferences), not an MSP's clients.

## The one principle

**Claude is the relationship model.** Memories enter the graph through `remember`,
to which *Claude itself* supplies the entities **and the edges between them**. No
second LLM extracts anything on the main path; types and relationships are written
deterministically from Claude's structured input (via `ainsert_custom_kg`). The
local Ollama model is **optional** — embeddings, plus the offline `recall`/
`extract_local` convenience paths. Everything Claude needs to *read* memory
(`search_memory` and the graph primitives) runs with **no LLM at all**, returning
raw context for Claude to synthesize.

Corollary: **preserve this.** Don't add a local extraction step to the `remember`
path. If you want local extraction, it stays behind `extract_local.py` and is
explicitly optional + review-first.

## Durability model (why this is safe to trust)

- **Journal-first.** `remember` appends to `data/memory_journal.jsonl` *before*
  touching the graph. If the graph write fails (Ollama down), the memory is still
  saved; `python rebuild.py` indexes it later.
- **Graph is derived + disposable.** `python rebuild.py` replays the journal and
  rebuilds `graph/` losslessly (verified: auto-stubbed endpoints survive, forgotten
  entities are dropped). Switch embedding backends? Wipe `graph/`, rebuild.
- **No approval gate** (unlike the MSP PoC). Devon asked for Claude to write directly, so
  there's no staging/approve step — the journal is the audit trail instead.

---

## How to *remember* well  (read before calling `remember`)

When you learn something durable about Devon, his work, or his world, model it as a
small graph, not a sentence. Good structure now = good recall later.

**Pick the right entity type** (closed set): `person, project, concept, tool, task,
goal, note, preference, resource, event, place, organization, skill, habit`.
Unknown/typo'd types fall back to `note` (a warning is returned) — prefer a real type.

**Tag the life-domain with `category`:** `gamedev, homelab, dev, work, learning,
gaming, personal, health, finance, social, creative, ideas` (unknown categories are
kept, so you can grow them).

**Add `tags`** freely (many per entity) for the cross-cutting stuff types/categories
don't capture.

**Always connect it.** A node with no edges is nearly invisible to graph retrieval.
Link new things to Devon, to the project they belong to, to the tools they use.
Recommended relations: `works_on, created_by, uses, part_of, depends_on, blocks,
related_to, knows, member_of, learned_from, interested_in, prefers, located_at,
attended, owns, references, inspired_by, next_step, about, mentions` (others allowed).

**Re-`remember` to update.** Writing an entity again **merges**: tags union, newest
description/type win. To connect two things you've already saved, use `link`
(or `remember` with only `relationships`). To remove something, use `forget`.

**Example call:**

```json
{
  "entities": [
    {"name": "Shader Atlas", "type": "project", "category": "gamedev",
     "tags": ["godot", "rendering", "active"],
     "description": "Tool that bakes material variants into a texture atlas for Godot."},
    {"name": "Godot", "type": "tool", "category": "gamedev", "tags": ["engine"]}
  ],
  "relationships": [
    {"source": "Devon", "target": "Shader Atlas", "relation": "works_on"},
    {"source": "Shader Atlas", "target": "Godot", "relation": "uses"}
  ],
  "context": "Devon started Shader Atlas to cut draw calls in his Godot game."
}
```

**To recall inside a session:** call `search_memory(query)` (no LLM), read the
returned entities/relationships/notes, and answer in your own words. Use
`get_entity` / `get_relationships` to drill in, `browse` to list a category/type,
`memory_stats` for the lay of the land.

---

## Commands

Run from the repo root (venv active). Ollama only needed for the quality embedding
backend and the optional LLM paths.

```bash
python seed_memory.py                  # starter memories -> journal + graph
python add_memory.py --name "Blender" --type tool --category gamedev --desc "..."
python add_memory.py --json '{"entities":[...],"relationships":[...]}'
python recall.py "what am I building?"          # no-LLM retrieval, pretty-printed
python recall.py "summarize my homelab" --llm   # local-model synthesis (needs Ollama)
python memory_health.py                # offline health: journal + graph, UNKNOWN%, isolated
python rebuild.py [--dry-run]          # rebuild graph/ from the journal (lossless)
python mcp_server.py                   # serve MCP on 0.0.0.0:8000 path "/"
python extract_local.py --file notes.md         # OPTIONAL local extraction (review-only)

python test_memory.py                  # offline pure tests (schema/store/journal/replay)
python test_integration.py             # end-to-end on the hash backend (no Ollama)
```

Backend switch (per graph — pick one): `PMEM_EMBED_BACKEND=ollama` (default,
quality) or `hash` (no service). Other env knobs in `config.py`
(`PMEM_DATA_DIR`, `PMEM_GRAPH_DIR`, `PMEM_OLLAMA_HOST`, `PMEM_LLM_MODEL`, …).

---

## Key files

| File | Role |
|---|---|
| `schema.py` | Taxonomy + normalization (`ENTITY_TYPES`, `CATEGORIES`, `RELATIONS`). Pure, testable. |
| `journal.py` | Append-only JSONL journal — the source of truth. Pure. |
| `memory_store.py` | `normalize_memory` → `build_fragment` (custom_kg) → `replay`/`build_custom_kg`/`check_integrity`. Pure. |
| `memory_api.py` | The async operations behind every tool/CLI. The `remember` write path lives here. |
| `lightrag_setup.py` | LightRAG instance; `embed_func` switches ollama/hash; optional `llm_func`. |
| `mcp_server.py` | FastMCP; thin wrappers over `memory_api`; mounted at `/`. |
| `rebuild.py` `seed_memory.py` `add_memory.py` `recall.py` `memory_health.py` `extract_local.py` | CLIs. |
| `test_memory.py` `test_integration.py` | Offline + end-to-end tests. |

---

## Critical gotchas

1. **Mount at `path="/"`.** Claude.ai POSTs to the root; FastMCP defaults to `/mcp`
   → Claude.ai 404s then shows a misleading OAuth error. (Carried over from the MSP PoC.)
2. **Restart `mcp_server.py` after a `rebuild.py`** (and re-toggle the connector
   after any tool change) — the running server holds an in-memory graph, and the
   connector caches the tool manifest. (Carried over from the MSP PoC.)
3. **One embedding backend per graph.** Vectors from `ollama` and `hash` aren't
   comparable. If you change `PMEM_EMBED_BACKEND`, wipe `graph/` and `rebuild.py`.
4. **`ainsert_custom_kg` MERGES.** Re-inserting an existing entity merges it (that's
   how updates work). For a clean rebuild, `rebuild.py` wipes `graph/` first.
5. **Don't re-stub an existing node.** A relationship to an already-typed node must
   reference it, not re-emit it as a generic `note` (LightRAG's merge would downgrade
   the type). `memory_api.remember` handles this via the `known`/`_resolve_exact`
   pass — preserve it. (This was a real bug; there's a test for it.)
6. **The journal must stay complete.** Auto-stubbed relationship endpoints are
   written to the journal too, so `rebuild.py` is lossless. Don't move stub creation
   to *after* the journal append.
7. **`recall`/`extract_local` need Ollama.** They degrade gracefully (clear message)
   when it's down; `search_memory` and the rest do not depend on it.

---

## Current state (verified)

- **Write path:** `remember`/`link`/`forget` deterministic, journaled, type-safe.
  Confirmed: a `person` is **not** downgraded to `note` by a later `link`.
- **Read path:** `search_memory` + graph primitives run with no LLM; the hash
  embedder ranks the seed graph sensibly.
- **Rebuild:** journal → graph is **lossless** (stub-preserving, forget-applying).
- **Seed graph:** 10 entities / 10 relationships, **0 UNKNOWN types, 0 isolated
  nodes**, types spread across person/project/tool/concept/preference.
- **Backends:** `ollama` (nomic-embed-text, 768-dim) default; `hash` zero-dep
  fallback proven for the full pipeline.
- **Not yet done (PoC posture):** no auth on the tunnel (single host/user); the
  optional local-LLM paths are untested in this environment (no Ollama here) but
  mirror the MSP PoC's working calls; embedding-backend migrations are manual (`rebuild.py`).

When you change behavior, **update this file and the relevant `docs/`** so the next
session starts from the truth.
