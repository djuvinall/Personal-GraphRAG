"""
rebuild.py — rebuild the LightRAG graph from the journal (the source of truth).

The journal (data/memory_journal.jsonl) is authoritative; the graph in graph/ is a
derived index. Run this when:
  * the graph is lost/corrupted,
  * you switched embedding backends (PMEM_EMBED_BACKEND),
  * you edited the journal by hand,
  * or you just want a clean, de-duplicated rebuild.

It replays every journal record (applying merges + forgets), builds one custom_kg,
wipes graph/, and re-inserts deterministically (embeddings only — no LLM).

    python rebuild.py            # rebuild from data/memory_journal.jsonl
    python rebuild.py --dry-run  # show what WOULD be built, write nothing
"""
import asyncio
import shutil
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import journal
import memory_store as ms
from config import GRAPH_DIR

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def plan():
    records = journal.read_all()
    ents, rels = ms.replay(records)
    kg = ms.build_custom_kg(ents, rels)
    problems = ms.check_integrity(kg)
    return records, ents, rels, kg, problems


async def rebuild(dry_run=False):
    records, ents, rels, kg, problems = plan()
    print(f"Journal records:     {len(records)}")
    print(f"Live entities:       {len(ents)}")
    print(f"Live relationships:  {len(rels)}")
    from collections import Counter
    hist = Counter(e["type"] for e in ents.values())
    print("Entity types:")
    for t, n in hist.most_common():
        print(f"  {n:4}  {t}")

    if problems:
        print(f"\nERROR — {len(problems)} integrity problem(s); refusing to rebuild:")
        for p in problems[:30]:
            print("  -", p)
        return

    if dry_run:
        print("\n--dry-run: nothing written.")
        return

    if GRAPH_DIR.exists():
        shutil.rmtree(GRAPH_DIR)
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)

    from lightrag_setup import create_rag
    rag = create_rag()
    await rag.initialize_storages()
    try:
        from lightrag.kg.shared_storage import initialize_pipeline_status
        await initialize_pipeline_status()
    except Exception:
        pass
    await rag.ainsert_custom_kg(kg)
    print(f"\nRebuilt graph at {GRAPH_DIR} "
          f"({len(kg['entities'])} entities, {len(kg['relationships'])} relationships).")
    print("Restart mcp_server.py to serve the rebuilt graph.")


if __name__ == "__main__":
    asyncio.run(rebuild(dry_run="--dry-run" in sys.argv))
