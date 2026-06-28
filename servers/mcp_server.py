"""
mcp_server.py — FastMCP server exposing your memory graph to Claude.

Thin transport layer over memory_api.py. The defining tool is `remember`: Claude
hands it the entities AND relationships it worked out from your conversation, and
they're written deterministically. No second extraction model, no separate
"relationship model" — Claude is the relationship model. The local Ollama model
is optional and only `recall` uses it.

Durability: every write is appended to data/memory_journal.jsonl FIRST (the source
of truth, survives an index failure), then indexed into the LightRAG graph. No
human approval gate — you asked for Claude to write directly. `python rebuild.py`
can always reconstruct the graph from the journal.

Run:  python mcp_server.py   (Streamable HTTP on 0.0.0.0:8000, path "/").
Expose via ngrok and add the bare HTTPS URL as a Claude.ai connector (OAuth blank).
"""
import json
import os
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from fastmcp import FastMCP
import memory_api as api

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

mcp = FastMCP("Personal GraphRAG")


def _j(d) -> str:
    return json.dumps(d, indent=2, default=str)


# --------------------------- WRITE (Claude-driven) -------------------------

@mcp.tool()
async def remember(entities=None, relationships=None, context: str = "",
                   origin: str = "conversation") -> str:
    """Save something to long-term memory. THIS is how Claude adds to the graph.

    Claude (not a local model) decides the structure and passes it in:

      entities: list of objects, each:
        { "name": str (required),
          "type": person|project|concept|tool|task|goal|note|preference|resource|
                  event|place|organization|skill|habit,
          "category": gamedev|homelab|dev|work|learning|gaming|personal|health|
                  finance|social|creative|ideas,
          "tags": [str, ...],
          "description": str }

      relationships: list of objects, each:
        { "source": entity name, "target": entity name,
          "relation": works_on|uses|knows|part_of|depends_on|related_to|member_of|
                  learned_from|prefers|located_at|owns|references|... ,
          "description": str (optional) }

      context: optional free-text sentence giving extra searchable background.

    Unknown types fall back to 'note', unknown categories are kept, and any
    relationship endpoint not defined as an entity is auto-stubbed — a write is
    never rejected. Re-remembering an entity MERGES it (tags union; newest
    description/type win). Returns a JSON summary of what was written.
    """
    return _j(await api.remember(entities=entities, relationships=relationships,
                                 context=context, origin=origin))


@mcp.tool()
async def link(source: str, target: str, relation: str = "related_to",
               description: str = "") -> str:
    """Connect two entities with a relationship (stubs either if new). A focused
    shortcut for when Claude just wants to add an edge. Same write path as remember."""
    return _j(await api.link(source, target, relation, description))


@mcp.tool()
async def forget(entity: str) -> str:
    """Remove an entity from memory (tombstoned in the journal, deleted from the
    live graph). The journal preserves the history."""
    return _j(await api.forget(entity))


@mcp.tool()
async def rename(old_name: str, new_name: str) -> str:
    """Rename an entity. Atomically: creates the new entity with the same
    metadata, re-links all relationships to the new name (journalled first so
    rebuild.py stays lossless), then forgets the old name.
    Returns counts of edges relinked."""
    return _j(await api.rename(old_name, new_name))


@mcp.tool()
async def merge(source: str, target: str) -> str:
    """Merge source entity into target. All of source's relationships are
    re-pointed to target (self-loops are dropped), then source is forgotten.
    target survives with its own name and metadata unchanged.
    Use this to deduplicate entities (e.g. 'Rewst' to 'Rewst Automation Platform')."""
    return _j(await api.merge(source, target))


# --------------------------- MAINTENANCE -----------------------------------

@mcp.tool()
async def find_similar(name: str, top_k: int = 6) -> str:
    """Surface entities that may be duplicates of the named entity.

    Searches the vector store for near-neighbours of name's embedding and
    returns candidates sorted by distance (lower = more similar). Use this
    to detect accidental duplicates before they accumulate, then consolidate
    with merge(). Scores are distances: < 0.25 is a strong duplicate suspect.
    """
    return _j(await api.find_similar(name, top_k))


@mcp.tool()
async def stale_entities(days: int = 90, limit: int = 30) -> str:
    """Return entities not updated in the journal for the last N days.

    Useful for periodic memory review: surfaces tasks that may be done,
    projects that may have stalled, or facts that may have changed.
    Pure journal read - no Ollama needed. Results sorted stalest-first.
    """
    return _j(await api.stale_entities(days, limit))


# --------------------------- READ (no LLM) ---------------------------------

@mcp.tool()
async def search_memory(query: str, top_k: int = 8) -> str:
    """Semantic search across your memory. NO LLM — embeds the query and returns
    the most relevant entities, relationships, and notes for Claude to reason over.
    The primary recall tool inside a Claude session. JSON:
    { entities:[...], relationships:[...], notes:[...] }."""
    return _j(await api.search_memory(query, top_k))


@mcp.tool()
async def get_entity(name: str) -> str:
    """Fetch one entity's stored attributes directly from the graph; fuzzy-suggests
    on a miss. No LLM."""
    return _j(await api.get_entity(name))


@mcp.tool()
async def get_relationships(entity: str, depth: int = 1, limit: int = 40) -> str:
    """List relationships around an entity (depth 1-3). Deterministic traversal, no LLM."""
    return _j(await api.get_relationships(entity, depth, limit))


@mcp.tool()
async def memory_stats() -> str:
    """Overview of your memory: totals, type + category breakdown, most-connected
    entities, and journal stats. No LLM, instant."""
    return _j(await api.memory_stats())


@mcp.tool()
async def browse(category: str = "", entity_type: str = "", tag: str = "",
                 limit: int = 50) -> str:
    """Browse entities filtered by category, type, and/or tag. No LLM. E.g.
    'everything in homelab' or 'all my open tasks'."""
    return _j(await api.browse(category, entity_type, tag, limit))


@mcp.tool()
async def recent_memories(n: int = 15) -> str:
    """The last n things written to memory, straight from the journal. No LLM."""
    return _j(await api.recent_memories(n))


# --------------------------- OPTIONAL LLM ----------------------------------

@mcp.tool()
async def recall(query: str, mode: str = "hybrid") -> str:
    """Answer from memory using the LOCAL model to synthesize prose (needs Ollama).
    Inside a Claude session prefer `search_memory` and let Claude write the answer.
    mode: local|global|hybrid|naive."""
    return _j(await api.recall(query, mode))


if __name__ == "__main__":
    port = int(os.environ.get("PMEM_PORT", "8000"))
    mcp.run(transport="http", host="0.0.0.0", port=port, path="/")
