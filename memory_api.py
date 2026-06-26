"""
memory_api.py — the memory operations, independent of any transport.

All the actual logic lives here as plain async functions returning plain dicts,
so it can be driven three ways without duplication:
  * mcp_server.py  — thin FastMCP tool wrappers (Claude over the tunnel)
  * the CLIs        — add_memory.py / recall.py / rebuild.py
  * tests           — call these directly with the hash backend, no Ollama

The headline operation is `remember`: Claude passes entities + relationships it
worked out itself; we journal then index them. No extraction model, no separate
relationship model — Claude is the relationship model.
"""
from __future__ import annotations
import json

import journal
import memory_store as ms
import schema
from config import EMBED_BACKEND

_rag = None


async def get_rag():
    """Lazily build + initialize the shared LightRAG instance."""
    global _rag
    if _rag is None:
        from lightrag_setup import create_rag
        _rag = create_rag()
        await _rag.initialize_storages()
        try:
            from lightrag.kg.shared_storage import initialize_pipeline_status
            await initialize_pipeline_status()
        except Exception:
            pass
    return _rag


def coerce_list(x):
    """Accept a list of dicts, a single dict, or a JSON string -> list."""
    if x is None:
        return []
    if isinstance(x, str):
        x = x.strip()
        if not x:
            return []
        try:
            x = json.loads(x)
        except json.JSONDecodeError:
            return []
    if isinstance(x, dict):
        return [x]
    return list(x)


def _score(r):
    v = r.get("distance", r.get("__metrics__"))
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# WRITE
# ---------------------------------------------------------------------------

async def _resolve_exact(g, name: str):
    """Return the existing graph node id for `name` (tolerating case), or None.
    Deliberately NOT fuzzy — we only want to recognize the SAME entity, never to
    guess a different one (which would create a wrong merge)."""
    for cand in (name, name.strip(), name.upper(), name.title(), name.lower()):
        if await g.has_node(cand):
            return cand
    return None


async def remember(entities=None, relationships=None, context="", origin="conversation") -> dict:
    record, warns = ms.normalize_memory(
        entities=coerce_list(entities), relationships=coerce_list(relationships),
        context=context, origin=origin)
    if not record["entities"] and not record["relationships"]:
        return {"ok": False, "error": "nothing to remember (no valid entities or relationships)",
                "warnings": warns}

    # Best-effort consult of the live graph BEFORE journaling, so we can (a) reuse
    # an existing canonical node (no case-duplicates), (b) never re-stub an
    # existing typed node as a generic 'note', and (c) record a stub for any
    # genuinely-new referenced endpoint IN THE JOURNAL — otherwise a rebuild would
    # lose it (the journal must be the complete source of truth). `known` tells
    # build_fragment which endpoints already exist and must be referenced, not emitted.
    rag = None
    known = set()
    try:
        rag = await get_rag()
        g = rag.chunk_entity_relation_graph
        supplied = {e["name"].lower() for e in record["entities"]}
        stubbed = set()
        for r in record["relationships"]:
            for side in ("source", "target"):
                ep = r[side]
                if ep.lower() in supplied:
                    continue
                canon = await _resolve_exact(g, ep)
                if canon:
                    r[side] = canon
                    known.add(canon.lower())
                elif ep.lower() not in stubbed:           # new endpoint -> journal a stub
                    stubbed.add(ep.lower())
                    record["entities"].append({
                        "name": ep, "type": schema.DEFAULT_TYPE,
                        "category": schema.DEFAULT_CATEGORY, "tags": [],
                        "description": "(referenced; details not yet recorded)"})
    except Exception:
        rag = None                                        # graph/embeddings offline

    record = journal.append(record)                       # durable; includes new stubs
    frag = ms.build_fragment(record, known=known)

    indexed, index_error = False, "graph index unavailable (embeddings offline) — run rebuild.py later"
    if rag is not None:
        try:
            await rag.ainsert_custom_kg(frag)
            indexed, index_error = True, None
        except Exception as ex:                           # index is retryable; journal already safe
            indexed, index_error = False, str(ex)

    return {
        "ok": True,
        "memory_id": record["id"],
        "entities_written": [e["entity_name"] for e in frag["entities"]],
        "relationships_written": [f"{r['src_id']} -[{r['keywords']}]-> {r['tgt_id']}"
                                  for r in frag["relationships"]],
        "indexed_to_graph": indexed,
        "index_error": index_error,
        "note": None if indexed else "Saved to journal; run `python rebuild.py` to index later.",
        "warnings": warns,
    }


async def link(source, target, relation="related_to", description="") -> dict:
    return await remember(relationships=[{"source": source, "target": target,
                          "relation": relation, "description": description}])


async def forget(entity: str) -> dict:
    journal.append({"op": "forget", "entity": entity})
    removed = False
    try:
        rag = await get_rag()
        await rag.adelete_by_entity(entity)
        removed = True
    except Exception:
        pass
    return {"ok": True, "forgot": entity, "removed_from_graph": removed}


async def forget_relationship(source: str, target: str, relation: str) -> dict:
    """Tombstone a specific relationship in the journal.

    The live LightRAG graph does not support single-edge deletion; the tombstone
    takes effect on the next `python rebuild.py`. The dashboard removes the edge
    from its view optimistically.
    """
    journal.append({"op": "forget_relationship",
                    "source": source, "target": target, "relation": relation})
    return {"ok": True,
            "forgot_relationship": f"{source} -[{relation}]-> {target}",
            "note": "tombstoned in journal; run rebuild.py to remove from graph index"}


# ---------------------------------------------------------------------------
# READ (no LLM)
# ---------------------------------------------------------------------------

async def search_memory(query: str, top_k: int = 8) -> dict:
    rag = await get_rag()
    top_k = max(1, min(int(top_k), 50))
    ents = await rag.entities_vdb.query(query, top_k=top_k)
    rels = await rag.relationships_vdb.query(query, top_k=top_k)
    chunks = await rag.chunks_vdb.query(query, top_k=top_k)
    return {
        "query": query,
        "entities": [{"name": e.get("entity_name"), "score": _score(e),
                      "text": e.get("content")} for e in ents],
        "relationships": [{"source": r.get("src_id"), "target": r.get("tgt_id"),
                           "score": _score(r), "text": r.get("content")} for r in rels],
        "notes": [{"score": _score(c), "text": c.get("content"),
                   "source": c.get("full_doc_id")} for c in chunks],
    }


async def _resolve_entity(g, name: str):
    if await g.has_node(name):
        return name
    for cand in (name.strip(), name.upper(), name.title(), name.lower()):
        if cand != name and await g.has_node(cand):
            return cand
    matches = await g.search_labels(name, limit=1)
    if matches and await g.has_node(matches[0]):
        return matches[0]
    return None


async def get_entity(name: str) -> dict:
    rag = await get_rag()
    g = rag.chunk_entity_relation_graph
    node_id = await _resolve_entity(g, name)
    if node_id is None:
        return {"found": False, "query": name, "suggestions": await g.search_labels(name, limit=8)}
    node = await g.get_node(node_id) or {}
    return {"found": True, "entity": node_id, "degree": await g.node_degree(node_id),
            "attributes": node}


async def get_relationships(entity: str, depth: int = 1, limit: int = 40) -> dict:
    rag = await get_rag()
    g = rag.chunk_entity_relation_graph
    start = await _resolve_entity(g, entity)
    if start is None:
        return {"found": False, "query": entity, "suggestions": await g.search_labels(entity, limit=8)}
    depth = max(1, min(int(depth), 3))
    limit = max(1, min(int(limit), 200))
    seen_nodes, seen_edges, rels, frontier = {start}, set(), [], [start]
    for _ in range(depth):
        nxt = []
        for node in frontier:
            for s, t in (await g.get_node_edges(node) or []):
                key = frozenset((s, t))
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edge = await g.get_edge(s, t) or {}
                neighbor = t if s == node else s
                rels.append({"source": s, "target": t, "relation": edge.get("keywords"),
                             "description": edge.get("description"), "weight": edge.get("weight")})
                if neighbor not in seen_nodes:
                    seen_nodes.add(neighbor)
                    nxt.append(neighbor)
                if len(rels) >= limit:
                    break
            if len(rels) >= limit:
                break
        frontier = nxt
        if len(rels) >= limit or not frontier:
            break
    return {"found": True, "entity": start, "depth": depth,
            "relationship_count": len(rels), "relationships": rels}


async def memory_stats() -> dict:
    rag = await get_rag()
    g = rag.chunk_entity_relation_graph
    G = await g._get_graph()
    type_counts, cat_counts = {}, {}
    for _, data in G.nodes(data=True):
        et = (data or {}).get("entity_type") or "unknown"
        type_counts[et] = type_counts.get(et, 0) + 1
        desc = (data or {}).get("description", "")
        if "category:" in desc:
            cat = desc.split("category:")[1].split(";")[0].split("]")[0].strip()
            if cat:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
    degrees = dict(G.degree())
    top = await g.get_popular_labels(limit=10)
    return {
        "total_entities": G.number_of_nodes(),
        "total_relationships": G.number_of_edges(),
        "entity_types": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        "categories": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
        "most_connected": [{"entity": n, "degree": degrees.get(n, 0)} for n in top],
        "journal": journal.stats(),
        "embed_backend": EMBED_BACKEND,
    }


async def browse(category="", entity_type="", tag="", limit=50) -> dict:
    rag = await get_rag()
    g = rag.chunk_entity_relation_graph
    G = await g._get_graph()
    cat, etype, tg = category.strip().lower(), entity_type.strip().lower(), tag.strip().lower()
    out = []
    for name, data in G.nodes(data=True):
        d = data or {}
        desc = (d.get("description") or "").lower()
        if etype and (d.get("entity_type") or "").lower() != etype:
            continue
        if cat and f"category: {cat}" not in desc:
            continue
        if tg and tg not in desc:
            continue
        out.append({"name": name, "type": d.get("entity_type"), "description": d.get("description")})
        if len(out) >= max(1, min(int(limit), 200)):
            break
    return {"filters": {"category": category, "entity_type": entity_type, "tag": tag},
            "count": len(out), "entities": out}


async def recent_memories(n: int = 15) -> dict:
    return {"recent": journal.recent(int(n))}


# ---------------------------------------------------------------------------
# OPTIONAL LLM synthesis (needs Ollama)
# ---------------------------------------------------------------------------

async def recall(query: str, mode: str = "hybrid") -> dict:
    from lightrag import QueryParam
    from lightrag_setup import ollama_up
    if not ollama_up():
        return {"ok": False, "answer": None,
                "error": "Ollama not reachable — use search_memory and synthesize, "
                         "or start Ollama with qwen2.5:3b pulled."}
    rag = await get_rag()
    tuned = dict(top_k=12, max_entity_tokens=2000, max_relation_tokens=2000,
                 max_total_tokens=6000, enable_rerank=False)
    answer = await rag.aquery(query, param=QueryParam(mode=mode, **tuned))
    return {"ok": True, "mode": mode, "answer": answer}
