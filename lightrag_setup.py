"""
lightrag_setup.py — the LightRAG instance for personal memory.

Two deliberate departures from the MSP PoC setup, both serving "personal + local-first":

  1. PLUGGABLE EMBEDDINGS. `PMEM_EMBED_BACKEND` selects:
       - "ollama" (default): nomic-embed-text, 768-dim — best retrieval quality.
       - "hash": a zero-dependency, deterministic feature-hash embedder. No
         service, no model download, always works. Lower quality, but it means
         the whole system runs (and the tests pass) on a machine with no Ollama.

  2. THE LLM IS OPTIONAL. Claude is the brain: it both *writes* memories
     (entities + relationships, no extraction model) and *reads* them (it calls
     the no-LLM `search_memory`, which returns raw graph context, and synthesizes
     the answer itself). The local qwen model is only invoked by the optional
     `recall` (local synthesis) and `extract` (local extraction) paths. If Ollama
     isn't running, those degrade gracefully; everything else keeps working.

Vectors from different backends are not comparable — pick one backend per graph.
If you change it, wipe graph/ and run `python rebuild.py`.
"""
import hashlib
import re

import aiohttp
import numpy as np
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc

from config import (GRAPH_DIR, EMBED_DIM, EMBED_MAX_TOKENS, EMBED_BACKEND,
                    OLLAMA_HOST, EMBED_MODEL, LLM_MODEL)
from schema import ENTITY_TYPES

# Personal entity vocabulary handed to LightRAG for the OPTIONAL local-extraction
# path (extract_local.py). The deterministic write path sets types in code and
# ignores this, exactly like the MSP PoC's spine.
ENTITY_TYPE_LIST = list(ENTITY_TYPES.keys())


# ---------------------------------------------------------------------------
# Backend 1 — zero-dependency feature-hash embedder.
# Bag-of-words + char-trigrams hashed into EMBED_DIM buckets with signed
# accumulation (the classic hashing trick), then L2-normalized. Deterministic,
# stdlib+numpy only. Good enough for keyword-overlap retrieval and for tests.
# ---------------------------------------------------------------------------
_word_re = re.compile(r"[a-z0-9]+")


def _hash_vec(text: str, dim: int) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    text = (text or "").lower()
    tokens = _word_re.findall(text)
    # whole words
    for tok in tokens:
        _bump(vec, tok, dim)
    # char trigrams give near-miss words partial overlap (e.g. plurals, typos)
    joined = " ".join(tokens)
    for i in range(len(joined) - 2):
        _bump(vec, joined[i:i + 3], dim, scale=0.5)
    n = np.linalg.norm(vec)
    if n > 0:
        vec /= n
    return vec


def _bump(vec, token, dim, scale=1.0):
    h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
    bucket = h % dim
    sign = 1.0 if (h // dim) % 2 == 0 else -1.0
    vec[bucket] += sign * scale


async def _hash_embed(texts: list) -> np.ndarray:
    return np.vstack([_hash_vec(t, EMBED_DIM) for t in texts]).astype(np.float32)


# ---------------------------------------------------------------------------
# Backend 2 — Ollama nomic-embed-text (identical to the MSP PoC's stack).
# ---------------------------------------------------------------------------
async def _ollama_embed(texts: list) -> np.ndarray:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{OLLAMA_HOST}/api/embed",
            json={"model": EMBED_MODEL, "input": texts},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            data = await resp.json()
            return np.array(data["embeddings"], dtype=np.float32)


async def embed_func(texts: list) -> np.ndarray:
    if EMBED_BACKEND == "hash":
        return await _hash_embed(texts)
    return await _ollama_embed(texts)


# ---------------------------------------------------------------------------
# Optional local LLM (qwen2.5:3b via Ollama) — only the `recall`/`extract`
# convenience paths call this. Keep the local model resident to avoid cold loads.
# ---------------------------------------------------------------------------
async def llm_func(prompt, system_prompt=None, history_messages=None, **kwargs) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in (history_messages or []):
        messages.append(m)
    messages.append({"role": "user", "content": prompt})
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{OLLAMA_HOST}/api/chat",
            json={"model": LLM_MODEL, "messages": messages, "stream": False,
                  "keep_alive": "30m", "options": {"num_ctx": 8192, "num_predict": 512}},
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            data = await resp.json()
            return data["message"]["content"]


def ollama_up() -> bool:
    """Best-effort sync check that Ollama is reachable (for friendly messages)."""
    import urllib.request
    try:
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def create_rag(working_dir=None) -> LightRAG:
    """Build the LightRAG instance. `working_dir` override isolates scratch graphs
    (used by the optional local extractor) from the live memory graph."""
    return LightRAG(
        working_dir=str(working_dir or GRAPH_DIR),
        llm_model_func=llm_func,
        llm_model_name=LLM_MODEL,
        llm_model_max_async=1,
        addon_params={"entity_types": ENTITY_TYPE_LIST},
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM,
            max_token_size=EMBED_MAX_TOKENS,
            func=embed_func,
        ),
    )
