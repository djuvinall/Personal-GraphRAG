"""
journal.py — the append-only memory journal (the SOURCE OF TRUTH).

Every write to the graph also lands here, one JSON object per line. The LightRAG
graph in graph/ is a *derived index*: if it's ever lost, corrupted, or you switch
embedding backends, `python rebuild.py` replays this journal and rebuilds it.

Design choices that matter for a *personal* memory you have to trust for years:
  * Append-only      — we never rewrite history; a "forget" is a new line, not a
                       deletion, so the timeline is auditable and reversible.
  * Human-readable   — JSONL you can open, grep, and diff in git.
  * Self-contained   — each line carries everything needed to replay it (no joins).

Op kinds:
  remember  {entities:[...], relationships:[...], context, origin}
  link      {relationships:[...]}                 (relationships-only remember)
  forget    {entity: "<canonical name>"}          (tombstone)

This module is pure stdlib — importable and testable without lightrag/ollama.
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import JOURNAL_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return "mem_" + uuid.uuid4().hex[:10]


def append(record: dict, path: Path | None = None) -> dict:
    """Append one record (adds id + ts if absent) and return it."""
    path = Path(path or JOURNAL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    record.setdefault("id", _new_id())
    record.setdefault("ts", _now())
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_all(path: Path | None = None) -> list[dict]:
    """Read every journal record in write order. Missing file -> []."""
    path = Path(path or JOURNAL_PATH)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # A corrupt line should never sink the whole memory — skip + note it.
            out.append({"op": "_corrupt", "raw": line})
    return out


def recent(n: int = 20, path: Path | None = None) -> list[dict]:
    """The last n journal records (most recent last)."""
    records = [r for r in read_all(path) if r.get("op") != "_corrupt"]
    return records[-n:]


def stats(path: Path | None = None) -> dict:
    """Quick counts over the journal, no graph needed."""
    records = read_all(path)
    counts: dict[str, int] = {}
    entities = 0
    relationships = 0
    for r in records:
        counts[r.get("op", "?")] = counts.get(r.get("op", "?"), 0) + 1
        entities += len(r.get("entities", []) or [])
        relationships += len(r.get("relationships", []) or [])
    return {
        "journal_path": str(path or JOURNAL_PATH),
        "total_records": len(records),
        "ops": counts,
        "entities_written": entities,
        "relationships_written": relationships,
    }
