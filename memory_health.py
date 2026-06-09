"""
memory_health.py — offline health check. No Ollama, no LightRAG, no network.

Reads two things and reports on them:
  * the journal (data/memory_journal.jsonl) — the source of truth
  * the LightRAG GraphML (graph/graph_chunk_entity_relation.graphml), if present

Flags the things that tend to rot in a personal KB: UNKNOWN-typed nodes, isolated
(unconnected) nodes, and a journal-vs-graph drift hint (rebuild if they diverge).

    python memory_health.py
"""
import sys
import xml.etree.ElementTree as ET
from collections import Counter

import journal
import memory_store as ms
from config import GRAPH_DIR

NS = {"g": "http://graphml.graphdrawing.org/xmlns"}


def _graphml_path():
    return GRAPH_DIR / "graph_chunk_entity_relation.graphml"


def read_graphml():
    """Return (type_counts, node_count, edge_count, isolated) or None if absent."""
    path = _graphml_path()
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    keymap = {k.get("id"): k.get("attr.name") for k in root.findall("g:key", NS)}
    g = root.find("g:graph", NS)

    def data_of(el):
        return {keymap.get(d.get("key")): (d.text or "") for d in el.findall("g:data", NS)}

    types, nodes, degree = Counter(), [], Counter()
    for n in g.findall("g:node", NS):
        nid = n.get("id")
        nodes.append(nid)
        t = (data_of(n).get("entity_type") or "UNKNOWN").strip().strip('"') or "UNKNOWN"
        types[t] += 1
    edges = g.findall("g:edge", NS)
    for e in edges:
        degree[e.get("source")] += 1
        degree[e.get("target")] += 1
    isolated = [n for n in nodes if degree[n] == 0]
    return types, len(nodes), len(edges), isolated


def main():
    print("=" * 64)
    print("Personal GraphRAG — memory health (offline)")
    print("=" * 64)

    # Journal (source of truth)
    js = journal.stats()
    print(f"\nJOURNAL  ({js['journal_path']})")
    print(f"  records: {js['total_records']}   ops: {js['ops']}")
    records = journal.read_all()
    ents, rels = ms.replay(records)
    print(f"  current-state (replayed): {len(ents)} entities, {len(rels)} relationships")
    jt = Counter(e["type"] for e in ents.values())
    if jt:
        print("  journal entity types: " + ", ".join(f"{t}={n}" for t, n in jt.most_common()))

    # Graph (derived index)
    gm = read_graphml()
    if gm is None:
        print("\nGRAPH    (none yet — run `python rebuild.py` or `python seed_memory.py`)")
    else:
        types, nodes, edges, isolated = gm
        print(f"\nGRAPH    ({_graphml_path()})")
        print(f"  nodes: {nodes}   edges: {edges}")
        print("  types: " + ", ".join(f"{t}={n}" for t, n in types.most_common()))
        unknown = types.get("UNKNOWN", 0)
        flag = "OK" if unknown == 0 else f"WARN — {unknown} UNKNOWN-typed nodes"
        print(f"  UNKNOWN-typed: {unknown}  [{flag}]")
        print(f"  isolated nodes: {len(isolated)}"
              + (f"  e.g. {isolated[:5]}" if isolated else "  [OK]"))
        # drift hint
        if nodes != len(ents):
            print(f"  NOTE — graph nodes ({nodes}) != journal entities ({len(ents)}); "
                  f"consider `python rebuild.py`.")
    print()


if __name__ == "__main__":
    main()
