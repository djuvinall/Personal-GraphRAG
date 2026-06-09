"""
test_memory.py — offline tests for the deterministic core.

No Ollama, no lightrag, no network — just the pure logic that decides what gets
written to your memory. Run after editing schema.py / memory_store.py / journal.py:

    python test_memory.py

Mirrors the spirit of Kosh's test_pipeline.py: prove the parts that must be
correct *without* needing the heavy runtime up.
"""
import tempfile
from pathlib import Path

import schema
import memory_store as ms
import journal


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        raise AssertionError(name)


def test_schema():
    print("schema:")
    t, w = schema.normalize_type("game")
    check("alias 'game' -> project", t == "project")
    t, w = schema.normalize_type("Person")
    check("'Person' -> person", t == "person" and w is None)
    t, w = schema.normalize_type("frobnicator")
    check("unknown type -> note + warning", t == "note" and w is not None)
    c, w = schema.normalize_category("Homelab")
    check("category 'Homelab' -> homelab", c == "homelab")
    c, w = schema.normalize_category("mood")
    check("unknown category kept + warned", c == "mood" and w is not None)
    check("tags normalized/deduped", schema.normalize_tags("Godot, godot #shader") == ["godot", "shader"])
    check("relation normalized", schema.normalize_relation("Works On") == "works_on")


def test_normalize_and_fragment():
    print("normalize + fragment:")
    rec, warns = ms.normalize_memory(
        entities=[
            {"name": "Devon", "type": "person", "category": "personal",
             "tags": ["owner"], "description": "Me."},
            {"name": "Personal GraphRAG", "type": "project", "category": "homelab",
             "tags": ["graphrag", "memory"], "description": "My memory database."},
            {"name": "Godot", "type": "tool", "tags": ["engine"]},
        ],
        relationships=[
            {"source": "Devon", "target": "Personal GraphRAG", "relation": "works_on"},
            {"source": "Personal GraphRAG", "target": "Godot", "relation": "uses"},
            # endpoint 'LightRAG' is NOT defined as an entity -> must auto-stub:
            {"source": "Personal GraphRAG", "target": "LightRAG", "relation": "uses"},
        ],
        context="Devon is building a personal GraphRAG memory store.",
        origin="conversation",
    )
    check("no blocking warnings", isinstance(warns, list))
    check("op is remember", rec["op"] == "remember")
    frag = ms.build_fragment(rec)
    names = {e["entity_name"] for e in frag["entities"]}
    check("3 supplied + 1 stub = 4 entities", len(frag["entities"]) == 4)
    check("LightRAG auto-stubbed", "LightRAG" in names)
    check("3 relationships kept", len(frag["relationships"]) == 3)
    problems = ms.check_integrity(frag, valid_types=schema.valid_types())
    check("fragment integrity clean", problems == [])
    # tags/category baked into the embedded text
    pg = next(e for e in frag["entities"] if e["entity_name"] == "Personal GraphRAG")
    check("category embedded in description", "homelab" in pg["description"])
    check("tags embedded in description", "graphrag" in pg["description"])


def test_replay_and_forget():
    print("replay + merge + forget:")
    records = [
        # First mention stubs 'Obsidian' via a relationship endpoint (type note).
        ms.normalize_memory(
            entities=[{"name": "Devon", "type": "person"}],
            relationships=[{"source": "Devon", "target": "Obsidian", "relation": "uses"}],
        )[0],
        # Later, 'Obsidian' is properly defined as a tool -> stub must upgrade.
        ms.normalize_memory(
            entities=[{"name": "Obsidian", "type": "tool", "tags": ["notes"]}],
        )[0],
        # Add then forget a throwaway entity.
        ms.normalize_memory(entities=[{"name": "Temp Idea", "type": "concept"}])[0],
        {"op": "forget", "entity": "Temp Idea"},
    ]
    ents, rels = ms.replay(records)
    check("Obsidian upgraded note->tool", ents["obsidian"]["type"] == "tool")
    check("forgotten entity gone", "temp idea" not in ents)
    check("relationship Devon->Obsidian survives", any(
        r["source"].lower() == "devon" and r["target"].lower() == "obsidian" for r in rels))
    kg = ms.build_custom_kg(ents, rels)
    check("rebuilt KG integrity clean", ms.check_integrity(kg) == [])


def test_journal_roundtrip():
    print("journal roundtrip:")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "j.jsonl"
        rec, _ = ms.normalize_memory(entities=[{"name": "X", "type": "note"}])
        journal.append(rec, path=p)
        journal.append({"op": "forget", "entity": "X"}, path=p)
        back = journal.read_all(p)
        check("two records persisted", len(back) == 2)
        check("ids assigned", all("id" in r for r in back))
        s = journal.stats(p)
        check("stats counts ops", s["ops"].get("remember") == 1 and s["ops"].get("forget") == 1)


if __name__ == "__main__":
    print("=" * 60)
    print("Personal GraphRAG — offline core tests")
    print("=" * 60)
    test_schema()
    test_normalize_and_fragment()
    test_replay_and_forget()
    test_journal_roundtrip()
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
