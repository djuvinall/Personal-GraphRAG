# Architecture & design rationale

This document covers the **why**, not the what. For the what — file roles,
commands, the taxonomy — see [`../README.md`](../README.md), [`../CLAUDE.md`](../CLAUDE.md),
and the other docs. The decisions below are the ones that shaped everything else.

## The problem this solves

I wanted Claude to have durable, structured memory about my life that survives
across sessions: people, projects, tools, decisions, preferences — and, crucially,
the **relationships** between them, so retrieval can follow edges instead of just
matching text. That's GraphRAG. The catch is that building a good knowledge graph
normally requires a strong model to do entity/relationship extraction, and I
didn't want to pay for a big model on every write or run one locally just to parse
my own notes.

## Decision 1 — Claude is the relationship model

**What:** the write path (`remember`) takes entities *and the edges between them*
as structured input and writes them deterministically (`ainsert_custom_kg`). No
second LLM extracts anything on the main path.

**Why:** extraction is the expensive, quality-critical part of GraphRAG, and a
strong model is already in the loop — Claude is the thing having the conversation.
It knows the context better than any extractor I could run, so asking it to emit
`{entities, relationships}` is both cheaper and *higher quality* than re-deriving
that structure from prose with a separate model.

**What this avoids:** I built an earlier MSP version of this and watched a weak 3B
model ignore the entity-type vocabulary and produce a graph full of generic,
mistyped nodes (`organization`/`artifact`/`content`) and junk hubs. The graph was
technically populated and practically unusable. The lesson: *if a small model sets
your types, your types will be wrong.* Here the types are set in code from
Claude's structured input, so that failure mode is structurally impossible on the
main path.

**Trade-off:** this only works because a capable model is already present at write
time. It's the right call for a memory that's written *through Claude*; it would be
the wrong call for batch-ingesting a pile of unstructured documents with no model
in the loop. For that case there's an explicit, optional, review-first escape
hatch (`extract_local.py`) that uses the local model — but it never touches the
deterministic main path.

## Decision 2 — Journal-first durability

**What:** every write appends one JSON line to `data/memory_journal.jsonl` *before*
the graph is touched. The journal is the source of truth; the LightRAG graph is a
derived index.

**Why:** this is personal memory I need to trust for years, and the graph index is
the fragile part — it depends on embeddings (Ollama), on LightRAG's on-disk
format, and on a chosen embedding backend. If I made the graph authoritative, an
Ollama outage or a format change could lose memories. By journaling first:

- A graph-write failure (Ollama down) doesn't lose the memory — it's already
  durable, and `rebuild.py` indexes it later.
- The graph is **disposable**: `python rebuild.py` replays the journal and
  reconstructs it losslessly. Switching embedding backends, recovering from
  corruption, or de-duplicating is just a rebuild.
- The journal is plain JSONL: greppable, diffable, and trivially backed up. The
  format you have to trust long-term is the simplest one.

**Why append-only:** a `forget` is a new tombstone line, not a deletion. History
stays auditable and reversible, and replay can apply forgets deterministically.

**Trade-off:** the journal grows unbounded and replay is O(history). For a
single-person memory that's a non-issue for years; at scale you'd compact it. The
design optimizes for trust and recoverability over write throughput, which is the
right priority for this use case.

## Decision 3 — The read path has no LLM

**What:** `search_memory` and the graph primitives (`get_entity`,
`get_relationships`, `memory_stats`, `browse`) return raw graph context with no
model in the loop. Claude reads that context and writes the answer itself.

**Why:** inside a Claude session, generation is already happening — adding a second
(local, weaker) model to synthesize an answer would only lower quality and add
latency and a hard Ollama dependency. The retriever's job is to *find and return*
the right subgraph; the reasoning belongs to the model that's already talking to
the user. So the read path embeds the query, does vector + graph lookup, and hands
back entities/edges/notes. Fast, deterministic, and it works even with no Ollama.

**Trade-off:** there's still a `recall` tool that *does* use the local model to
synthesize prose, for querying the server outside a Claude session. It's optional
and clearly marked; it degrades with a friendly message when Ollama is down.

## Decision 4 — Pluggable embeddings, with a zero-dependency fallback

**What:** `PMEM_EMBED_BACKEND` selects `ollama` (nomic-embed-text, 768-dim, the
quality default) or `hash` (a deterministic feature-hash embedder, stdlib+numpy).

**Why:** I didn't want the project to be unrunnable — or untestable in CI — on a
machine without Ollama. The `hash` backend uses the classic hashing trick
(bag-of-words + char-trigrams into signed buckets, L2-normalized) pinned to the
same 768-dim width as nomic-embed-text, so the store layout is identical. Retrieval
quality is lower, but the *entire pipeline* runs and the full end-to-end test suite
passes with no external service. The quality path is one `rebuild.py` away.

**Constraint this creates:** vectors from the two backends aren't comparable, so
it's one backend per graph. Changing it means wiping `graph/` and rebuilding — and
because the graph is disposable by design (Decision 2), that's cheap.

## Decision 5 — No approval gate

The MSP version had a human approve-before-commit staging step, because it ingested
data that could be wrong. This version deliberately doesn't: I asked for Claude to
write directly, because the write path is deterministic and the journal is a
complete audit trail I can edit and replay. The safety story here is *recoverability*
(journal + rebuild), not *gatekeeping*.

## How the pieces enforce this

The codebase keeps the "pure" logic (no LightRAG/Ollama imports) separate and
unit-tested, so the rules above are verifiable without the heavy runtime:

- `schema.py` — the closed type vocabulary + normalization. Pure.
- `journal.py` — append-only JSONL. Pure.
- `memory_store.py` — normalize → `build_fragment` (custom_kg) → `replay` →
  `build_custom_kg` → `check_integrity`. Pure, so "a stub never downgrades an
  existing type" and "rebuild is lossless" are covered by `test_memory.py`.
- `memory_api.py` — the async operations; the only layer that touches LightRAG.
- `lightrag_setup.py` — the one place embeddings/LLM are wired, with the backend
  switch.
- `mcp_server.py` — thin FastMCP wrappers; no logic of its own.

A subtle correctness rule lives in the write path: a relationship endpoint that
already exists as a typed node must be *referenced*, not re-emitted as a generic
`note`, or LightRAG's merge would downgrade its type. That was a real bug; the
`known`/`_resolve_exact` pass fixes it and `test_integration.py` guards it.

## Limitations & honest edges

- **Single user, single host, no auth on the tunnel.** This is a PoC posture. Auth
  and a stable hostname are the top roadmap items before any wider exposure.
- **Replay is O(history)** and the journal is uncompacted (fine for personal scale).
- **Entity identity is name-based** (case-insensitive). Re-using a name merges;
  varying it makes a second node. Keep names canonical.
- **The optional local-LLM paths** (`recall`, `extract_local`) mirror the proven
  MSP call patterns but are the least-exercised part of this repo, since the design
  goal was to make them optional.
