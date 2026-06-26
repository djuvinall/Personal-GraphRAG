---
title: Personal GraphRAG — Code Review
date: 2026-06-26
branch: WEBUI
reviewer: Claude
---

# Personal GraphRAG — Code Review (2026-06-26)

Full pass over the repo on branch `WEBUI`. Overall the codebase is in good shape:
clean separation (`core` / `servers` / `scripts` / `tests`), the journal-first
durability model is sound, the deterministic write path is well-guarded, and the
offline test suite passes. The issues below are real but mostly operational /
deployment-level rather than design flaws.

I implemented the **safe, high-value fixes** directly (see *Changes implemented*).
The **risky / your-call items** (git state, live server, deprecations) are listed
under *Recommended — not done* with exact commands.

---

## Findings by severity

### 🔴 Blockers

**1. Your live memory MCP is erroring — `No module named 'lightrag_setup'`.**
Every call to the connected Personal-GraphRAG MCP (`search_memory`, `memory_stats`,
etc.) failed during this review with that import error. The *repo* code is correct
— `servers/mcp_server.py` inserts `core/` onto `sys.path` before importing
`memory_api`, and the lazy `from lightrag_setup import create_rag` resolves from
there. So the running process is almost certainly one of:

- started from a directory/runner where `__file__`-relative path insertion didn't
  land `core/` on `sys.path`, or
- a **pre-refactor** server process still running the old flat layout (gotcha #2:
  "restart `mcp_server.py` after changes").

*Mitigation shipped:* I hardened `core/memory_api.py` to insert its own directory
onto `sys.path` at import time, so the lazy `lightrag_setup` import can't fail this
way regardless of how the process is launched. **You still need to restart the live
MCP server** from the current `servers/mcp_server.py` and re-toggle the connector
for the fix to take effect.

**2. The `WEBUI` branch has every tracked file staged for deletion.**
`git status` shows all 35 files as `deleted` in the index, with the same files
present as untracked. If you commit this state, the next commit wipes the repo.
This is recoverable and harmless until committed — the working tree is intact — but
do **not** `git commit -a` here. Fix command under *Recommended*.

### 🟠 High

**3. The dashboard WebSocket (`/ws`) streamed memory contents with no auth.**
REST endpoints are session-guarded, but `/ws` was not — the comment said
"localhost-only," yet the server binds `0.0.0.0` and you expose it over ngrok. Any
client that reached the tunnel could subscribe to `/ws` and receive every
entity/relationship delta in real time. **Fixed:** `/ws` now rejects unauthenticated
clients (close code 1008) whenever `WEB_UI_PASSWORD` is set, matching the REST guard.

**4. CI was broken after the refactor.** `.github/workflows/ci.yml` still ran
`python test_memory.py` / `python test_integration.py` at the repo root, but the
refactor moved them into `tests/`. Every CI run would fail at the test step.
**Fixed:** updated both paths to `tests/…`. Note CI still only triggers on `main`,
so it won't run for `WEBUI` pushes/PRs until merged or the branch filter is widened.

### 🟡 Medium / performance

**5. The journal was fully replayed on every graph request.** `_graph_data()` read
and folded the entire journal (`jrn.read_all()` → `ms.replay()`) on *every*
`/api/graph`, `/api/entities`, and `/api/relationships` call. The SPA hits
`/api/graph` on load and after edits; the watcher already does deltas, so this was
pure repeated work that grows linearly with journal size. **Fixed:** added a
`(mtime, size)`-keyed cache around the replay. Because the journal is append-only,
any write changes its stat and transparently invalidates the cache — no manual
invalidation needed.

**6. The graph view became a hairball (your screenshot).** Root causes: all node
labels *and* all edge labels rendered at every zoom level, plus low-value
auto-stub/leaf nodes crowding the canvas. **Fixed** — see *Decluttering* below.

### 🟢 Low / housekeeping

- **`servers/dashboard.py` uses the deprecated `@app.on_event("startup")`.** Works
  today; emits a deprecation warning and will break on a future FastAPI. Migrate to
  the `lifespan=` context manager when convenient. (Left as-is — behavior change,
  your call.)
- **Default session secret is insecure** (`"change-me-set-WEB_UI_SECRET"`). Fine for
  localhost; set `WEB_UI_SECRET` before any tunnel exposure. The startup banner only
  warns about a missing `WEB_UI_PASSWORD`, not the secret — consider warning on both.
- **`/api/entities` and `/api/relationships` are dead endpoints** — the SPA only uses
  `/api/graph`. Harmless, but each recomputes the whole graph (now cached). Drop or
  document them.
- **`_compute_graph_data()` recomputes degree from edges** while the same numbers are
  already derived client-side on deltas — fine, just noting the duplication.
- **No rate/size guard on `remember`/`link` via REST** — acceptable for single-user,
  worth a note before any multi-user posture.

---

## Decluttering the graph (implemented)

Approach chosen: **smart defaults + opt-in controls** (keeps the Cytoscape stack,
no data-model change). Changes in `servers/dashboard.html`:

- **Edge labels off by default.** They were the single biggest source of text noise.
  Toggle still available in the toolbar.
- **Zoom-aware labels.** Node and edge labels use `min-zoomed-font-size`, so they
  fade out when zoomed out and appear as you zoom in. The canvas reads as colored
  nodes at a glance, detail on demand.
- **Hover-to-focus.** Hovering a node dims everything except it and its neighbors and
  force-shows their labels — quick local inspection without entering Ego mode.
- **Density controls** (new toolbar group): a **Min-degree** slider (range auto-set
  from your data), **Hide leaves** (degree ≤ 1), and **Hide stubs** (the
  "(referenced; details not yet recorded)" placeholders). These compose with the
  existing Full / Ego / Filtered modes.
- **More breathing room.** Tuned the COSE layout (longer ideal edges, higher
  repulsion, component spacing) so clusters separate instead of piling up.

Net effect: default view is colored nodes with edges and no label spam; you zoom,
hover, or use the density sliders to pull in detail. Nothing is deleted — it's all
view-state.

---

## Changes implemented

| File | Change | Why |
|---|---|---|
| `servers/dashboard.html` | Edge labels off by default; zoom-aware labels; hover-focus; min-degree / hide-leaves / hide-stubs controls; layout tuning | Declutter the graph |
| `servers/dashboard.py` | `(mtime,size)`-keyed cache around the journal replay | Stop re-replaying the journal every request |
| `servers/dashboard.py` | `/ws` now requires auth when a password is set | Close unauth memory-data exposure over the tunnel |
| `core/memory_api.py` | Self-insert `core/` onto `sys.path` at import | Harden against the live `lightrag_setup` import failure |
| `.github/workflows/ci.yml` | Point test steps at `tests/` | CI was broken by the refactor |

All changes verified: `python -m py_compile` clean on edited Python, offline suite
(`tests/test_memory.py`) passes, dashboard JS passes `node --check`.

---

## Recommended — not done (your call)

**Fix the git staging (do this before any commit on `WEBUI`):**

```bash
git reset            # unstage the mass-deletion; working tree already matches HEAD → clean
git status           # confirm: "nothing to commit, working tree clean"
```

**Restart the live MCP server** from the refactored entrypoint, then re-toggle the
Claude.ai connector so it re-reads the tool manifest:

```bash
python servers/mcp_server.py
```

**Other low-risk follow-ups:** migrate `dashboard.py` off `@app.on_event` to
`lifespan=`; widen CI's branch filter (or merge `WEBUI` to `main`) so it actually
runs; set `WEB_UI_SECRET` and warn on it at startup.

---

## Scope note

You asked for a review + safe fixes; I kept to that. I did **not** touch the
deterministic write/read core logic (`memory_store.py`, `schema.py`, `journal.py`,
the `remember`/`build_fragment` path) — it's correct, tested, and the guardrails
(no-downgrade merges, journaled stubs, lossless rebuild) are the part most worth not
disturbing. The git cleanup and the live-server restart are the two things only you
should run.
