# TODO — Personal GraphRAG

Backlog items that are well-scoped but not yet started. Each entry includes
enough design context to pick up cold.

---

## Journal Compaction Script

**File:** `scripts/compact_journal.py`

**Why:** `ms.replay()` is O(history) — every call reads and processes the
entire `data/memory_journal.jsonl`. At a few hundred entries this is instant;
at ~5,000+ entries startup latency and dashboard load will be noticeable.

**Design:**
- Read the full journal and run `ms.replay()` to get the final state
  (`ents_by_key`, `rels`) — this is the lossless snapshot
- Write a new `data/memory_journal.jsonl.compacted` that contains:
  1. One `remember` record per surviving entity (from `ents_by_key`), timestamped now
  2. One `link` record per surviving relationship (from `rels`)
  3. A header record `{op: "compaction", original_records: N, compacted_at: ts}`
- Verify the compacted journal replays to the same state (integrity check)
- Only then replace the live journal: `mv journal.jsonl journal.jsonl.bak && mv journal.jsonl.compacted journal.jsonl`
- Keep the `.bak` until the user confirms everything looks right

**Key constraint:** `forget` tombstones are intentionally dropped — that's the
point of compaction. The `.bak` preserves the original history if needed.

**Suggested CLI:**
```bash
python scripts/compact_journal.py [--dry-run]
```
`--dry-run` prints the before/after record counts without touching any files.

---

## Community Cluster Summaries

**Why:** As the graph grows, "what are my active areas right now?" becomes hard
to answer from raw entities. Microsoft GraphRAG's key contribution was running
community detection and writing a short summary per cluster — making the graph
queryable at a higher level of abstraction.

**Design:**
- Use NetworkX (already a LightRAG transitive dependency) to run community
  detection on the graph: `networkx.algorithms.community.greedy_modularity_communities(G)`
- For each community above a minimum size (e.g., ≥ 4 entities):
  - Collect entity names + descriptions
  - Call Claude (or the local Ollama model) to write a 2–3 sentence summary
  - Write the summary as a `note` entity named e.g. `"Cluster: Gamedev Projects 2026"`
    with `tags: ["cluster-summary", "auto-generated"]`
- Run as a scheduled task or on-demand via `python scripts/cluster_summaries.py`

**Key constraint:** cluster summary notes should be tagged `auto-generated` so
they can be bulk-forgotten on re-run and not accumulate stale summaries.

**Suggested schedule:** weekly, after any significant batch of new memories.
