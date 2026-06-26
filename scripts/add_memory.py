"""
add_memory.py — add a memory from the command line.

The primary way memories get added is Claude calling the `remember` MCP tool. This
CLI is for manual entry, scripting, and testing. Two input styles:

  # Simple: one entity (+ optional one relationship)
  python add_memory.py --name "Blender" --type tool --category gamedev \
      --tags "3d,modeling" --desc "3D suite I use for game assets" \
      --rel-target "Devon" --rel "owns"

  # Full: a JSON payload (entities + relationships), the same shape `remember` takes
  python add_memory.py --json '{"entities":[{"name":"Devon","type":"person"}],
      "relationships":[{"source":"Devon","target":"Blender","relation":"uses"}]}'

  echo '{...}' | python add_memory.py --json -      # read JSON from stdin
"""
import argparse
import asyncio
import json
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import memory_api as api

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def run(args):
    if args.json is not None:
        raw = sys.stdin.read() if args.json == "-" else args.json
        payload = json.loads(raw)
        res = await api.remember(
            entities=payload.get("entities"),
            relationships=payload.get("relationships"),
            context=payload.get("context", ""),
            origin=payload.get("origin", "cli"),
        )
    else:
        if not args.name:
            print("Provide --name (and optionally --type/--category/--tags/--desc) "
                  "or use --json.")
            return
        entities = [{"name": args.name, "type": args.type, "category": args.category,
                     "tags": args.tags, "description": args.desc}]
        relationships = []
        if args.rel_target:
            relationships.append({"source": args.name, "target": args.rel_target,
                                  "relation": args.rel, "description": args.rel_desc})
        res = await api.remember(entities=entities, relationships=relationships,
                                 context=args.context, origin="cli")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Add a memory to the personal graph.")
    ap.add_argument("--json", help="full JSON payload (or '-' for stdin)")
    ap.add_argument("--name")
    ap.add_argument("--type", default="note")
    ap.add_argument("--category", default="")
    ap.add_argument("--tags", default="", help="comma- or space-separated")
    ap.add_argument("--desc", default="")
    ap.add_argument("--context", default="")
    ap.add_argument("--rel-target", default="", help="create an edge to this entity")
    ap.add_argument("--rel", default="related_to", help="relation type for --rel-target")
    ap.add_argument("--rel-desc", default="")
    asyncio.run(run(ap.parse_args()))
