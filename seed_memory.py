"""
seed_memory.py — plant a handful of starter memories so the graph isn't empty.

Everything here is grounded in what's already known from your setup (your stated
preferences, this project, and its tech stack) — nothing invented. It's a
demonstration of the schema and a useful starting point; edit the SEEDS list
freely, or wipe it all with:  rm data/memory_journal.jsonl && rm -rf graph/

    python seed_memory.py            # add the seeds (idempotent-ish: re-running
                                     # merges, it won't duplicate nodes)
"""
import asyncio
import sys

import memory_api as api

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Each seed is one `remember` call: a cluster of entities + the edges between them.
SEEDS = [
    dict(
        context="Devon owns this personal memory database and is comfortable with "
                "IT, game development, and systems topics.",
        entities=[
            {"name": "Devon", "type": "person", "category": "personal", "tags": ["owner", "me"],
             "description": "Owner of this memory graph. Into IT, game dev, and systems."},
            {"name": "Concise & direct responses", "type": "preference", "category": "personal",
             "tags": ["communication", "style"],
             "description": "Prefers concise, direct, peer-to-peer answers with minimal "
                            "hedging; fundamentals before complexity; blunt feedback."},
        ],
        relationships=[
            {"source": "Devon", "target": "Concise & direct responses", "relation": "prefers"},
        ],
    ),
    dict(
        context="Personal GraphRAG is Devon's self-hosted memory graph, adapted from "
                "an earlier MSP GraphRAG PoC and optimized for personal use.",
        entities=[
            {"name": "Personal GraphRAG", "type": "project", "category": "homelab",
             "tags": ["memory", "graphrag", "active"],
             "description": "Self-hosted personal knowledge graph for persistent memory. "
                            "Claude writes entities + relationships directly; local model optional."},
            {"name": "MSP GraphRAG PoC", "type": "project", "category": "homelab",
             "tags": ["graphrag", "msp", "source"],
             "description": "The MSP GraphRAG PoC this personal version was forked from."},
        ],
        relationships=[
            {"source": "Devon", "target": "Personal GraphRAG", "relation": "works_on"},
            {"source": "Personal GraphRAG", "target": "MSP GraphRAG PoC", "relation": "inspired_by",
             "description": "Adapted the spine/custom-KG approach from that PoC."},
        ],
    ),
    dict(
        context="The Personal GraphRAG stack: LightRAG for hybrid retrieval, Ollama "
                "for local embeddings (and optional generation), FastMCP for the "
                "Claude connector, ngrok for the tunnel.",
        entities=[
            {"name": "LightRAG", "type": "tool", "category": "homelab", "tags": ["rag", "retrieval"],
             "description": "Hybrid vector + graph retrieval engine; custom_kg insert is the write path."},
            {"name": "Ollama", "type": "tool", "category": "homelab", "tags": ["local-llm", "embeddings"],
             "description": "Serves local models. nomic-embed-text for embeddings; qwen2.5:3b optional generation."},
            {"name": "FastMCP", "type": "tool", "category": "homelab", "tags": ["mcp", "server"],
             "description": "Python MCP server framework exposing memory tools to Claude.ai."},
            {"name": "ngrok", "type": "tool", "category": "homelab", "tags": ["tunnel"],
             "description": "Public HTTPS tunnel from Claude.ai to the local MCP server."},
            {"name": "GraphRAG", "type": "concept", "category": "learning", "tags": ["rag", "knowledge-graph"],
             "description": "Retrieval-augmented generation over a knowledge graph rather than flat chunks."},
            {"name": "Model Context Protocol", "type": "concept", "category": "learning", "tags": ["mcp", "tools"],
             "description": "Protocol letting Claude call external tools — here, the memory read/write tools."},
        ],
        relationships=[
            {"source": "Personal GraphRAG", "target": "LightRAG", "relation": "uses"},
            {"source": "Personal GraphRAG", "target": "Ollama", "relation": "uses",
             "description": "Local embeddings; optional local generation."},
            {"source": "Personal GraphRAG", "target": "FastMCP", "relation": "uses"},
            {"source": "Personal GraphRAG", "target": "ngrok", "relation": "uses"},
            {"source": "Personal GraphRAG", "target": "GraphRAG", "relation": "part_of"},
            {"source": "Personal GraphRAG", "target": "Model Context Protocol", "relation": "uses"},
            {"source": "Devon", "target": "GraphRAG", "relation": "interested_in"},
        ],
    ),
]


async def main():
    total_e = total_r = 0
    for seed in SEEDS:
        res = await api.remember(**seed)
        total_e += len(res.get("entities_written", []))
        total_r += len(res.get("relationships_written", []))
        print(f"+ {res['memory_id']}: {len(res.get('entities_written', []))} entities, "
              f"{len(res.get('relationships_written', []))} relationships")
    print(f"\nSeeded {total_e} entity-writes and {total_r} relationship-writes "
          f"across {len(SEEDS)} memories.")
    print("Try:  python recall.py \"what is Devon building?\"   |   python memory_health.py")


if __name__ == "__main__":
    asyncio.run(main())
