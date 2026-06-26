"""
config.py — paths + embedding config for Personal GraphRAG.

This is the *personal-memory* sibling of an MSP GraphRAG PoC I built. Where that PoC
models an MSP's companies/tickets/devices, this models ONE person's life: people,
projects, ideas, tools, tasks, notes, preferences. Single user, single host,
frictionless writes (Claude writes directly), append-only journal for safety.

Everything here is env-overridable so you can point the store at a different
folder or swap the embedding backend without editing code.
"""
import os
from pathlib import Path

BASE_DIR   = Path(__file__).parent
DATA_DIR   = Path(os.environ.get("PMEM_DATA_DIR",  BASE_DIR / "data"))
GRAPH_DIR  = Path(os.environ.get("PMEM_GRAPH_DIR", BASE_DIR / "graph"))

# The append-only journal is the SOURCE OF TRUTH. The LightRAG graph is a
# derived, disposable index that can be rebuilt from the journal at any time
# (python rebuild.py). Keep the journal; the graph is regenerable.
JOURNAL_PATH = Path(os.environ.get("PMEM_JOURNAL", DATA_DIR / "memory_journal.jsonl"))

# ---------------------------------------------------------------------------
# Embedding backend (see lightrag_setup.py).
#   "ollama" -> nomic-embed-text via local Ollama (quality default; needs Ollama).
#   "hash"   -> zero-dependency deterministic embedder (always works, no service;
#               lower retrieval quality — meant for tests / no-Ollama machines).
# Pick ONE per graph: vectors from different backends are not comparable, so if
# you switch, wipe graph/ and run `python rebuild.py`.
# ---------------------------------------------------------------------------
EMBED_BACKEND = os.environ.get("PMEM_EMBED_BACKEND", "ollama").lower()

# nomic-embed-text emits 768-dim vectors. The hash embedder is pinned to the
# same width so the store layout is identical regardless of backend.
EMBED_DIM        = int(os.environ.get("PMEM_EMBED_DIM", "768"))
EMBED_MAX_TOKENS = 8192

# Ollama (only used when EMBED_BACKEND="ollama" or for the optional `recall`
# local-LLM synthesis path). Models match the MSP PoC's stack so one Ollama install
# serves both projects.
OLLAMA_HOST = os.environ.get("PMEM_OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.environ.get("PMEM_EMBED_MODEL", "nomic-embed-text")
LLM_MODEL   = os.environ.get("PMEM_LLM_MODEL",   "qwen2.5:3b")

# Create the dirs we own on import (mirrors the MSP PoC's config.py convenience).
for _d in (DATA_DIR, GRAPH_DIR):
    _d.mkdir(parents=True, exist_ok=True)
