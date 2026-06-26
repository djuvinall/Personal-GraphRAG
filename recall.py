"""
recall.py — query your memory from the command line.

By default this does NO-LLM retrieval (the same path Claude uses): it embeds your
query and prints the most relevant entities, relationships, and notes. Add --llm
to have the local Ollama model synthesize a prose answer.

    python recall.py "what is Devon building?"
    python recall.py "my note-taking tools" --top-k 12
    python recall.py "summarize my homelab projects" --llm   # needs Ollama
"""
import argparse
import asyncio
import sys

import memory_api as api

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def run(query, top_k, use_llm, mode):
    if use_llm:
        res = await api.recall(query, mode=mode)
        if not res.get("ok"):
            print(res.get("error"))
        else:
            print(res["answer"])
        return

    res = await api.search_memory(query, top_k=top_k)
    print(f"\nQUERY: {res['query']}\n" + "=" * 60)
    if res["entities"]:
        print("\nENTITIES:")
        for e in res["entities"]:
            print(f"  [{e['score']}] {e['name']}")
            if e.get("text"):
                print(f"      {e['text'][:140]}")
    if res["relationships"]:
        print("\nRELATIONSHIPS:")
        for r in res["relationships"]:
            print(f"  [{r['score']}] {r['source']} -> {r['target']}")
            if r.get("text"):
                print(f"      {str(r['text'])[:140]}")
    if res["notes"]:
        print("\nNOTES:")
        for n in res["notes"]:
            print(f"  [{n['score']}] {str(n['text'])[:160]}")
    if not (res["entities"] or res["relationships"] or res["notes"]):
        print("\n(nothing found — the graph may be empty; try `python seed_memory.py`)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Query your personal memory graph.")
    ap.add_argument("query", help="what to recall")
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--llm", action="store_true", help="synthesize an answer with the local model (needs Ollama)")
    ap.add_argument("--mode", default="hybrid", help="LLM mode: local|global|hybrid|naive")
    args = ap.parse_args()
    asyncio.run(run(args.query, args.top_k, args.llm, args.mode))
