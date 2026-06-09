"""
memory_store.py — turn Claude-supplied memories into a LightRAG graph.

This is the piece that realizes the core requirement: **Claude is the relationship
model.** When Claude learns something worth keeping, it hands this module a small
structured payload — a few entities and the edges between them — and we write it
deterministically. No second LLM extracts entities; no separate "relationship
model" runs. The local Ollama model is optional and only shows up for embeddings
(quality) and the optional `recall`/`extract` paths.

Responsibilities (all pure — no lightrag/ollama imports, so it's unit-testable):
  * normalize     a raw payload against schema.py (types/categories/tags/relations)
  * build_fragment a LightRAG custom_kg dict for ONE memory (incremental insert)
  * replay        fold the whole journal into current-state entities + relationships
                  (applies merges and forgets), for full rebuilds
  * build_custom_kg + check_integrity   the rebuild + safety net

The LightRAG `custom_kg` shape (entities / relationships / chunks) and field names
mirror the proven Kosh build_kg.py exactly, so `rag.ainsert_custom_kg(...)` accepts
it unchanged. The only LLM-free write path — types are set in code, never guessed.
"""
from __future__ import annotations
from datetime import datetime, timezone

import schema


# ---------------------------------------------------------------------------
# Normalization — raw Claude/CLI payload -> clean structured records + warnings.
# ---------------------------------------------------------------------------

def normalize_entity(raw: dict) -> tuple[dict, list[str]]:
    """Clean one entity dict. Returns (entity, warnings). Never raises."""
    warns: list[str] = []
    name = (raw.get("name") or raw.get("entity") or raw.get("title") or "").strip()
    if not name:
        return {}, ["entity skipped: no name"]

    etype, w = schema.normalize_type(raw.get("type") or raw.get("entity_type"))
    if w:
        warns.append(f"{name}: {w}")
    cat, w = schema.normalize_category(raw.get("category"))
    if w:
        warns.append(f"{name}: {w}")
    tags = schema.normalize_tags(raw.get("tags"))
    desc = (raw.get("description") or raw.get("desc") or "").strip()

    return {"name": name, "type": etype, "category": cat, "tags": tags,
            "description": desc}, warns


def normalize_relationship(raw: dict) -> tuple[dict, list[str]]:
    """Clean one relationship dict. Returns (rel, warnings)."""
    src = (raw.get("source") or raw.get("src") or raw.get("from") or "").strip()
    tgt = (raw.get("target") or raw.get("tgt") or raw.get("to") or "").strip()
    if not src or not tgt:
        return {}, [f"relationship skipped: missing endpoint ({src!r} -> {tgt!r})"]
    rel = schema.normalize_relation(raw.get("relation") or raw.get("type") or raw.get("keywords"))
    desc = (raw.get("description") or raw.get("desc") or f"{src} {rel.replace('_', ' ')} {tgt}").strip()
    return {"source": src, "target": tgt, "relation": rel, "description": desc}, []


def normalize_memory(entities=None, relationships=None, context="", origin="conversation",
                     ts: str | None = None) -> tuple[dict, list[str]]:
    """Normalize a full memory payload into a journal-ready record.

    Returns (record, warnings). `record` is exactly what gets appended to the
    journal and is sufficient on its own to rebuild the graph fragment.
    """
    warns: list[str] = []
    ents, rels = [], []
    for e in (entities or []):
        ne, w = normalize_entity(e)
        warns += w
        if ne:
            ents.append(ne)
    for r in (relationships or []):
        nr, w = normalize_relationship(r)
        warns += w
        if nr:
            rels.append(nr)

    op = "link" if (rels and not ents) else "remember"
    record = {
        "op": op,
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "origin": origin or "conversation",
        "entities": ents,
        "relationships": rels,
        "context": (context or "").strip(),
    }
    return record, warns


# ---------------------------------------------------------------------------
# Rendering — bake type/category/tags into the text so they're embedded and
# therefore searchable, while the structured truth lives in the journal.
# ---------------------------------------------------------------------------

def render_description(e: dict) -> str:
    body = e.get("description", "").strip()
    meta = f"[type: {e['type']}; category: {e['category']}"
    if e.get("tags"):
        meta += f"; tags: {', '.join(e['tags'])}"
    meta += "]"
    if body:
        return f"{e['name']} — {body}  {meta}"
    return f"{e['name']}  {meta}"


def _source_id(record: dict, fallback_origin="conversation") -> str:
    ts = record.get("ts", "")
    date = ts[:10] if ts else datetime.now(timezone.utc).date().isoformat()
    origin = record.get("origin") or fallback_origin
    return f"memory/{date}/{origin}"


# ---------------------------------------------------------------------------
# Fragment builder — ONE memory -> custom_kg for incremental ainsert_custom_kg.
# ---------------------------------------------------------------------------

def build_fragment(record: dict, known: set | None = None) -> dict:
    """Build a LightRAG custom_kg dict for a single journal record.

    `known` is a set of lower-cased entity names that ALREADY EXIST in the live
    graph. Endpoints in `known` are referenced by the relationship but NOT
    re-emitted as entities — critical, because re-emitting an existing node as a
    minimal stub would let LightRAG's merge DOWNGRADE its real type (e.g. a
    `person` becoming a generic `note`). Endpoints that are neither supplied nor
    known are genuinely new, so we stub them as `note` (typed, never UNKNOWN);
    they get upgraded automatically the next time they're `remember`ed in full.
    """
    known = {k.lower() for k in (known or set())}
    src = _source_id(record)
    by_name = {e["name"].lower(): e for e in record.get("entities", [])}
    entities, chunks, relationships = [], [], []
    seen = set()

    def emit_entity(e: dict):
        key = e["name"].lower()
        if key in seen:
            return
        seen.add(key)
        desc = render_description(e)
        entities.append({"entity_name": e["name"], "entity_type": e["type"],
                         "description": desc, "source_id": src})
        chunks.append({"content": desc, "source_id": src, "source_chunk_index": 0})

    for e in record.get("entities", []):
        emit_entity(e)

    for r in record.get("relationships", []):
        for endpoint in (r["source"], r["target"]):
            key = endpoint.lower()
            if key in seen or key in known:
                continue                      # supplied already, or exists in graph
            if key in by_name:
                emit_entity(by_name[key])
            else:
                emit_entity({"name": endpoint, "type": schema.DEFAULT_TYPE,
                             "category": schema.DEFAULT_CATEGORY, "tags": [],
                             "description": "(referenced; details not yet recorded)"})
        relationships.append({"src_id": r["source"], "tgt_id": r["target"],
                              "description": r["description"], "keywords": r["relation"],
                              "weight": 1.0, "source_id": src})

    # An optional free-text context chunk gives retrieval extra surface area.
    if record.get("context"):
        chunks.append({"content": record["context"], "source_id": src, "source_chunk_index": 1})

    # Guarantee at least one chunk carries `src` so relationship source mapping
    # resolves (avoids LightRAG's "UNKNOWN source_id" warning on edge-only writes).
    if relationships and not chunks:
        summary = "; ".join(f"{r['src_id']} {r['keywords']} {r['tgt_id']}"
                            for r in relationships)
        chunks.append({"content": summary, "source_id": src, "source_chunk_index": 0})

    return {"entities": entities, "relationships": relationships, "chunks": chunks}


# ---------------------------------------------------------------------------
# Replay — fold the journal into current-state, for full rebuilds.
# ---------------------------------------------------------------------------

def replay(records: list[dict]) -> tuple[dict, list[dict]]:
    """Fold journal records into (entities_by_name, relationships).

    Merge rules (latest-wins, but never downgrade):
      type      explicit type beats the default 'note'; otherwise most-recent wins
      category  most-recent non-default wins
      tags      union of all seen
      desc      most-recent non-empty wins (full history stays in the journal)
    `forget` tombstones an entity and drops edges that touch it.
    """
    ents: dict[str, dict] = {}          # key: name.lower()
    rels: dict[tuple, dict] = {}        # key: (src.lower, tgt.lower, relation)

    def merge_entity(e: dict):
        k = e["name"].lower()
        cur = ents.get(k)
        if not cur:
            ents[k] = dict(e)
            return
        # type: don't let a generic stub overwrite a specific type
        if e["type"] != schema.DEFAULT_TYPE:
            cur["type"] = e["type"]
        if e.get("category") and e["category"] != schema.DEFAULT_CATEGORY:
            cur["category"] = e["category"]
        cur["tags"] = schema.normalize_tags((cur.get("tags") or []) + (e.get("tags") or []))
        if e.get("description"):
            cur["description"] = e["description"]
        # keep the earliest display name for stability (case), already set.

    for r in records:
        op = r.get("op")
        if op == "forget":
            name = (r.get("entity") or "").lower()
            ents.pop(name, None)
            for key in [k for k in rels if name in (k[0], k[1])]:
                rels.pop(key, None)
        elif op in ("remember", "link"):
            for e in r.get("entities", []):
                if e.get("name"):
                    merge_entity(e)
            for rel in r.get("relationships", []):
                key = (rel["source"].lower(), rel["target"].lower(), rel["relation"])
                rels[key] = dict(rel)

    # Drop relationships whose endpoints no longer exist (forgotten, never added).
    live = set(ents)
    rels = {k: v for k, v in rels.items() if k[0] in live and k[1] in live}
    return ents, list(rels.values())


def build_custom_kg(entities_by_name: dict, relationships: list[dict],
                    source="memory/rebuild") -> dict:
    """Build a FULL custom_kg from replayed current-state (used by rebuild.py)."""
    entities, chunks = [], []
    for e in entities_by_name.values():
        desc = render_description(e)
        entities.append({"entity_name": e["name"], "entity_type": e["type"],
                         "description": desc, "source_id": source})
        chunks.append({"content": desc, "source_id": source, "source_chunk_index": 0})
    rels = [{"src_id": r["source"], "tgt_id": r["target"], "description": r["description"],
             "keywords": r["relation"], "weight": 1.0, "source_id": source}
            for r in relationships]
    return {"entities": entities, "relationships": rels, "chunks": chunks}


def check_integrity(kg: dict, valid_types: set | None = None) -> list[str]:
    """Return a list of problems; empty list means the fragment is sound."""
    problems = []
    names = {e["entity_name"].lower() for e in kg["entities"]}
    seen = set()
    for e in kg["entities"]:
        k = e["entity_name"].lower()
        if k in seen:
            problems.append(f"duplicate entity: {e['entity_name']}")
        seen.add(k)
        vt = valid_types if valid_types is not None else schema.valid_types()
        if e["entity_type"] not in vt:
            problems.append(f"invalid type {e['entity_type']!r} on {e['entity_name']}")
    for r in kg["relationships"]:
        if r["src_id"].lower() not in names:
            problems.append(f"dangling src: {r['src_id']} -> {r['tgt_id']}")
        if r["tgt_id"].lower() not in names:
            problems.append(f"dangling tgt: {r['src_id']} -> {r['tgt_id']}")
    return problems
