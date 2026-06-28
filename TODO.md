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

---

## Dashboard: Cascade Drag Repulsion

**File:** `servers/dashboard.html` — `_buildCy()` drag event handler

**Why:** The current live-drag handler only pushes nodes within 280px of the
*dragged* node. If a pushed node lands on top of a third node, that third node
doesn't move — the cascade stops at depth 1. The result is that manual
repositioning can create new overlaps one hop away.

**Design:**
- After pushing a node during drag, add it to a "dirty" set
- Run a second pass over only the dirty set's neighbors to check for new overlaps
- Repeat until no new overlaps are introduced (or a max-depth cap of 3–4)
- This is essentially a BFS ripple: dragged node → pushed neighbors → their
  overlapping neighbors → and so on
- Keep a visited set so nodes aren't double-pushed in the same drag event frame

**Rough implementation:**
```javascript
cy.on('drag', 'node', function(e) {
  var queue = [e.target];
  var visited = new Set([e.target.id()]);
  for (var depth = 0; depth < 4 && queue.length; depth++) {
    var nextQueue = [];
    queue.forEach(function(source) {
      var sp = source.position(), sw2 = source.width() / 2;
      cy.nodes().not(source).forEach(function(n) {
        if (visited.has(n.id())) return;
        var np = n.position();
        if (Math.abs(np.x - sp.x) > 300 || Math.abs(np.y - sp.y) > 300) return;
        var dx = np.x - sp.x, dy = np.y - sp.y;
        var dist = Math.sqrt(dx*dx + dy*dy) || 0.001;
        var minDist = sw2 + n.width() / 2 + 16;
        if (dist < minDist) {
          var push = (minDist - dist) * 0.6;
          n.position({ x: np.x + (dx/dist)*push, y: np.y + (dy/dist)*push });
          nextQueue.push(n);
          visited.add(n.id());
        }
      });
    });
    queue = nextQueue;
  }
});
```

**Performance note:** BFS depth cap is critical — uncapped this becomes O(n²)
per mousemove frame. Depth 3–4 with the 300px bounding-box cull is safe for
~200 nodes.
