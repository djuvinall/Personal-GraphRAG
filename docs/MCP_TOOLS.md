# MCP_TOOLS — the 10 tools Claude gets

Served by `mcp_server.py` (thin wrappers over `memory_api.py`). All return JSON
strings. Grouped by what they touch and whether they need the local model.

---

## Write — Claude-driven, deterministic (no extraction model)

### `remember(entities=None, relationships=None, context="", origin="conversation")`
The headline tool. Claude supplies the structure; it's journaled then indexed.

- `entities`: list of `{name, type, category, tags, description}` (only `name`
  required). `type` ∈ the 14 entity types; `category` ∈ the 12 life-domains; both
  tolerate unknowns (type→`note`+warning, category kept+warning).
- `relationships`: list of `{source, target, relation, description}`. Endpoints not
  given as entities are auto-stubbed (typed `note`) **and journaled**, so rebuilds
  stay lossless. Endpoints that already exist are referenced, not re-typed.
- `context`: optional free-text sentence, embedded for extra recall surface.

Returns `{ok, memory_id, entities_written, relationships_written, indexed_to_graph,
index_error, warnings}`. If embeddings are offline, `indexed_to_graph=false` but the
memory is safe in the journal (`rebuild.py` indexes it later).

Re-`remember`ing a name **merges** (tags union; newest description/type win) — this
is how you update.

### `link(source, target, relation="related_to", description="")`
Shortcut to add a single edge between two things (stubbing either if new). Same
write path as `remember`.

### `forget(entity)`
Tombstone an entity in the journal and delete it from the live graph. The journal
keeps the history; a rebuild applies the forget.

---

## Read — no LLM (Claude synthesizes the answer)

### `search_memory(query, top_k=8)`
The primary recall tool in a Claude session. Embeds the query and returns the most
relevant **entities**, **relationships**, and **notes** — raw context, no
generation. Claude reads it and answers.

```json
{ "query": "...",
  "entities":      [{"name","score","text"}],
  "relationships": [{"source","target","score","text"}],
  "notes":         [{"score","text","source"}] }
```

### `get_entity(name)`
One entity's stored attributes (type, description, source, degree), resolving
case/spacing. On a miss, returns fuzzy `suggestions`.

### `get_relationships(entity, depth=1, limit=40)`
The neighborhood around an entity. `depth` 1–3 (1 = direct neighbors). Deterministic
graph traversal.

### `memory_stats()`
Totals, entity-type histogram, category histogram, the most-connected entities, and
journal stats. Instant. Good first call to orient.

### `browse(category="", entity_type="", tag="", limit=50)`
List entities filtered by any combination of category / type / tag. E.g. "all my
open tasks" → `browse(entity_type="task", tag="active")`.

### `recent_memories(n=15)`
The last `n` journal records — "what have I been saving lately", straight from the
source of truth.

---

## Optional — needs the local model (Ollama)

### `recall(query, mode="hybrid")`
Has the **local** qwen model synthesize a prose answer from the graph. Useful when
querying the server *outside* a Claude session. Inside a Claude session, prefer
`search_memory` and let Claude write the answer. Degrades with a clear message if
Ollama is down. `mode`: `local | global | hybrid | naive`.

---

## Typical Claude flow

1. User says something memorable → Claude calls **`remember`** with entities + edges.
2. User asks a question → Claude calls **`search_memory`** (maybe `get_entity` /
   `get_relationships` to drill in) → answers in its own words.
3. User says "I'm done with X" → Claude calls **`forget`**.

The local model is never required for any of this — it's optional sugar.
