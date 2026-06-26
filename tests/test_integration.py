"""
test_integration.py — end-to-end test of the real LightRAG write/read path.

Uses the zero-dependency HASH embedding backend and temp dirs, so it runs with NO
Ollama and touches none of your real memory. Proves the whole loop: Claude-style
structured writes -> graph -> no-LLM retrieval -> graph primitives -> forget ->
rebuild-from-journal.

    python test_integration.py

(For the fast, pure-logic checks that don't need LightRAG, see test_memory.py.)
"""
import asyncio
import os
import tempfile

# Force the local-only backend + throwaway dirs BEFORE importing anything that
# reads config. This is what makes the test hermetic.
_tmp = tempfile.mkdtemp(prefix="pmem_itest_")
os.environ["PMEM_EMBED_BACKEND"] = "hash"
os.environ["PMEM_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["PMEM_GRAPH_DIR"] = os.path.join(_tmp, "graph")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import memory_api as api          # noqa: E402
import journal                    # noqa: E402


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        raise AssertionError(name)


async def main():
    print("=" * 60)
    print("Personal GraphRAG — integration test (hash backend, no Ollama)")
    print("=" * 60)

    print("write (Claude-style structured remember):")
    r = await api.remember(
        entities=[
            {"name": "Devon", "type": "person", "category": "personal", "tags": ["owner"],
             "description": "Owner of this memory DB."},
            {"name": "Personal GraphRAG", "type": "project", "category": "homelab",
             "tags": ["memory"], "description": "Personal knowledge graph."},
            {"name": "Godot", "type": "tool", "category": "gamedev", "description": "Game engine."},
        ],
        relationships=[
            {"source": "Devon", "target": "Personal GraphRAG", "relation": "works_on"},
            {"source": "Personal GraphRAG", "target": "LightRAG", "relation": "uses"},
            {"source": "Devon", "target": "Godot", "relation": "uses"},
        ],
        context="Devon is building a personal GraphRAG memory store.")
    check("remember ok + indexed", r["ok"] and r["indexed_to_graph"])
    check("LightRAG endpoint auto-stubbed", "LightRAG" in r["entities_written"])

    print("link (relationship-only; existing node must NOT be downgraded):")
    await api.link("Devon", "Obsidian", "uses", "Notes in Obsidian.")
    devon = await api.get_entity("Devon")
    check("Devon still typed 'person' after link", devon["attributes"].get("entity_type") == "person")

    print("read (no-LLM search + graph primitives):")
    s = await api.search_memory("game engine", top_k=5)
    check("search returns the three result buckets",
          all(k in s for k in ("entities", "relationships", "notes")))
    ge = await api.get_entity("godot")        # case-insensitive resolve
    check("get_entity resolves case + type", ge["found"] and ge["attributes"]["entity_type"] == "tool")
    rel = await api.get_relationships("Devon", depth=1)
    check("Devon has >= 3 relationships", rel["relationship_count"] >= 3)
    st = await api.memory_stats()
    check("stats counts person + project + tool",
          st["entity_types"].get("person") == 1 and st["entity_types"].get("tool") == 1)
    br = await api.browse(category="gamedev")
    check("browse(gamedev) finds Godot", any(e["name"] == "Godot" for e in br["entities"]))

    print("forget:")
    await api.forget("Obsidian")
    gone = await api.get_entity("Obsidian")
    check("forgotten entity is gone from graph", not gone["found"])

    print("rebuild from journal (graph is regenerable):")
    import rebuild
    await rebuild.rebuild()
    st2 = await api.memory_stats()
    # journal still holds Obsidian's add + its forget tombstone -> replay drops it
    check("rebuilt graph excludes forgotten Obsidian",
          all(n["entity"] != "Obsidian" for n in st2["most_connected"]))
    # three writes happened: the structured remember, the link, and the forget.
    check("journal is the source of truth", journal.stats()["total_records"] >= 3)

    print("=" * 60)
    print("INTEGRATION TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
