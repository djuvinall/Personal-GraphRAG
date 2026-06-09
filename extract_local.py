"""
extract_local.py — OPTIONAL local-model extraction (the "local model as an
optional step").

The primary write path is Claude: it reads your conversation and calls `remember`
with structured entities + relationships. This module is the fallback for when you
want to ingest a blob of unstructured text WITHOUT a Claude session — it asks the
local Ollama model (qwen2.5:3b) to propose the structure, then runs it through the
exact same deterministic write path (normalize -> journal -> graph).

Because the local 3B model is weak, this defaults to --review (print the proposal,
write nothing). Add --commit to actually write. That keeps a human/Claude in the
loop, matching the project's approve-before-trust ethos.

    python extract_local.py --file notes.md            # review only (no write)
    python extract_local.py --text "Met Sam about..."  --commit
    echo "..." | python extract_local.py --commit

Requires Ollama running with qwen2.5:3b pulled.
"""
import argparse
import asyncio
import json
import re
import sys

import schema
import memory_api as api

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROMPT = """You extract a small knowledge graph from a person's note for their \
personal memory database. Return ONLY valid JSON, no prose, no code fences.

Allowed entity types: {types}
Allowed categories: {cats}
Common relations: {rels}

JSON shape:
{{
  "entities": [
    {{"name": "...", "type": "<one allowed type>", "category": "<one category>",
      "tags": ["..."], "description": "..."}}
  ],
  "relationships": [
    {{"source": "<entity name>", "target": "<entity name>", "relation": "<relation>",
      "description": "..."}}
  ]
}}

Rules:
- Only extract entities clearly present in the note. Prefer few, high-quality nodes.
- Every relationship's source and target must be an entity you listed.
- If unsure of a type, use "note". Keep names short and canonical.

NOTE:
\"\"\"
{text}
\"\"\"
"""


def _parse_json(raw: str) -> dict:
    """Pull the first JSON object out of the model's output, tolerating fences."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    start = raw.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


async def extract(text: str) -> dict:
    from lightrag_setup import llm_func, ollama_up
    if not ollama_up():
        return {"_error": "Ollama not reachable. Start it (ollama serve) with "
                "qwen2.5:3b pulled, or add memories via Claude / add_memory.py."}
    prompt = PROMPT.format(
        types=", ".join(schema.ENTITY_TYPES),
        cats=", ".join(schema.CATEGORIES),
        rels=", ".join(list(schema.RELATIONS)[:14]),
        text=text.strip()[:6000],
    )
    out = await llm_func(prompt)
    parsed = _parse_json(out)
    if not parsed:
        return {"_error": "Could not parse JSON from the local model.", "_raw": out[:500]}
    return parsed


async def run(args):
    if args.file:
        text = open(args.file, encoding="utf-8", errors="ignore").read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()
    if not text.strip():
        print("No input text.")
        return

    proposal = await extract(text)
    if "_error" in proposal:
        print(proposal["_error"])
        if proposal.get("_raw"):
            print("--- raw model output ---\n" + proposal["_raw"])
        return

    print("PROPOSED (from local model):")
    print(json.dumps(proposal, indent=2))

    if not args.commit:
        print("\n--review (default): nothing written. Re-run with --commit to save, "
              "or hand this JSON to add_memory.py --json after editing.")
        return

    res = await api.remember(entities=proposal.get("entities"),
                             relationships=proposal.get("relationships"),
                             context="", origin="local-extract")
    print("\nWRITTEN:")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Optional local-model extraction into memory.")
    ap.add_argument("--file", help="text/markdown file to extract from")
    ap.add_argument("--text", help="inline text to extract from")
    ap.add_argument("--commit", action="store_true", help="actually write (default: review only)")
    asyncio.run(run(ap.parse_args()))
