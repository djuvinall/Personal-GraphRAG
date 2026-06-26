"""
dashboard.py — Personal GraphRAG web UI (port 5000).

Standalone FastAPI app; run alongside mcp_server.py (different port).

Features
--------
* Session auth gated by WEB_UI_PASSWORD env var (open if unset)
* REST CRUD backed by memory_api.py — same journal-first write path as MCP tools
* Graph dump via memory_store.replay() — no LightRAG / Ollama required to READ
* WebSocket delta push — watches data/memory_journal.jsonl for new lines and
  sends structured deltas ({op: upsert|forget|forget_relationship, ...}) so the
  browser updates incrementally without a full reload
* Serves dashboard.html from the same directory

Run
---
  python dashboard.py

Environment variables
---------------------
  WEB_UI_PASSWORD   Password for the login form (no auth if unset)
  WEB_UI_SECRET     Session signing key (change in production; default is insecure)
  WEB_UI_PORT       Port (default 5000)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Set

# ── make sibling modules importable ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

import journal as jrn
import memory_api as api
import memory_store as ms
from config import JOURNAL_PATH

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

# ── config ────────────────────────────────────────────────────────────────────
WEB_UI_PASSWORD = os.environ.get("WEB_UI_PASSWORD", "")
SECRET_KEY      = os.environ.get("WEB_UI_SECRET",   "change-me-set-WEB_UI_SECRET")
HTML_PATH       = Path(__file__).parent / "dashboard.html"
_JOURNAL        = Path(JOURNAL_PATH)

app = FastAPI(title="Personal GraphRAG Dashboard", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400 * 30)


# ── WebSocket connection manager ──────────────────────────────────────────────
class _WSManager:
    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, msg: dict) -> None:
        dead: Set[WebSocket] = set()
        for ws in self._active:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._active -= dead


manager = _WSManager()


# ── auth helpers ──────────────────────────────────────────────────────────────
def _authed(request: Request) -> bool:
    if not WEB_UI_PASSWORD:
        return True
    return bool(request.session.get("authed"))


def _guard(request: Request) -> None:
    if not _authed(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


# ── graph data (journal replay — no LightRAG needed) ─────────────────────────
def _graph_data() -> dict[str, Any]:
    """Replay the journal and return nodes + edges with degree counts.

    Edge source/target are normalised to the canonical display name (the name
    stored on the entity) so Cytoscape IDs always match — journal entries can
    reference the same entity with different casing across writes.
    """
    records = jrn.read_all()
    ents_by_key, rels = ms.replay(records)

    # lowercase → canonical display name, so edge endpoints match node IDs
    canon: dict[str, str] = {k: e["name"] for k, e in ents_by_key.items()}

    degrees: dict[str, int] = {}
    for r in rels:
        for side in (r["source"].lower(), r["target"].lower()):
            degrees[side] = degrees.get(side, 0) + 1

    nodes = [
        {
            "id":          e["name"],
            "type":        e["type"],
            "category":    e["category"],
            "tags":        e["tags"],
            "description": e["description"],
            "degree":      degrees.get(k, 0),
        }
        for k, e in ents_by_key.items()
    ]
    edges = [
        {
            "source":      canon.get(r["source"].lower(), r["source"]),
            "target":      canon.get(r["target"].lower(), r["target"]),
            "relation":    r["relation"],
            "description": r.get("description", ""),
        }
        for r in rels
    ]
    return {"nodes": nodes, "edges": edges}


# ── journal delta helpers ─────────────────────────────────────────────────────
def _record_to_delta(record: dict) -> dict | None:
    op = record.get("op")
    if op == "forget":
        return {"type": "delta", "op": "forget",
                "entity": record.get("entity", "")}
    if op == "forget_relationship":
        return {"type": "delta", "op": "forget_relationship",
                "source":   record.get("source", ""),
                "target":   record.get("target", ""),
                "relation": record.get("relation", "")}
    if op in ("remember", "link"):
        return {"type":          "delta",
                "op":            "upsert",
                "entities":      record.get("entities", []),
                "relationships": record.get("relationships", []),
                "ts":            record.get("ts", "")}
    return None


# ── background journal watcher ────────────────────────────────────────────────
async def _journal_watcher() -> None:
    """Poll the journal every second; broadcast a delta for each new line."""
    last_pos: int = _JOURNAL.stat().st_size if _JOURNAL.exists() else 0

    while True:
        await asyncio.sleep(1)
        try:
            if not _JOURNAL.exists():
                continue
            size = _JOURNAL.stat().st_size
            if size <= last_pos:
                continue
            with _JOURNAL.open("r", encoding="utf-8") as f:
                f.seek(last_pos)
                new_text = f.read()
            last_pos = size
            for line in new_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    delta = _record_to_delta(json.loads(line))
                    if delta:
                        await manager.broadcast(delta)
                except Exception:
                    pass
        except Exception:
            pass


@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(_journal_watcher())


# ── auth routes ───────────────────────────────────────────────────────────────
_LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GraphRAG — Login</title>
  <link rel="stylesheet"
        href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.2/css/bootstrap.min.css">
  <style>
    body {{ background: #0d1117; display:flex; align-items:center;
            justify-content:center; height:100vh; margin:0; }}
    .card {{ background:#161b22; border:1px solid #30363d; color:#e6edf3;
             width:340px; border-radius:12px; padding:2rem; }}
    .card h4 {{ font-weight:700; margin-bottom:1.5rem; text-align:center; }}
    .form-control {{ background:#0d1117; border-color:#30363d; color:#e6edf3; }}
    .form-control:focus {{ background:#0d1117; color:#e6edf3;
                           border-color:#388bfd; box-shadow:none; }}
    .btn-primary {{ background:#238636; border-color:#238636; }}
    .btn-primary:hover {{ background:#2ea043; border-color:#2ea043; }}
    .err {{ color:#f85149; font-size:.875rem; margin-top:.5rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h4>🧠 Personal GraphRAG</h4>
    {error}
    <form method="post" action="/login">
      <div class="mb-3">
        <input type="password" name="password" class="form-control"
               placeholder="Password" autofocus required>
      </div>
      <button type="submit" class="btn btn-primary w-100">Sign in</button>
    </form>
  </div>
</body>
</html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if _authed(request):
        return RedirectResponse("/", status_code=302)
    err_html = f'<p class="err">{error}</p>' if error else ""
    return HTMLResponse(_LOGIN_HTML.format(error=err_html))


@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    pw = form.get("password", "")
    if pw == WEB_UI_PASSWORD:
        request.session["authed"] = True
        return RedirectResponse("/", status_code=302)
    return RedirectResponse("/login?error=Incorrect+password", status_code=302)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ── main page ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not _authed(request):
        return RedirectResponse("/login", status_code=302)
    if not HTML_PATH.exists():
        return HTMLResponse("<h1>dashboard.html not found</h1>", status_code=500)
    return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))


# ── REST API ──────────────────────────────────────────────────────────────────
@app.get("/api/graph")
async def api_graph(request: Request):
    _guard(request)
    return _graph_data()


@app.get("/api/entities")
async def api_entities(request: Request):
    _guard(request)
    return {"entities": _graph_data()["nodes"]}


@app.get("/api/relationships")
async def api_relationships(request: Request):
    _guard(request)
    return {"relationships": _graph_data()["edges"]}


@app.post("/api/remember")
async def api_remember(request: Request):
    _guard(request)
    body = await request.json()
    result = await api.remember(
        entities=body.get("entities"),
        relationships=body.get("relationships"),
        context=body.get("context", ""),
        origin="dashboard",
    )
    return result


@app.post("/api/forget")
async def api_forget(request: Request):
    _guard(request)
    body = await request.json()
    name = body.get("entity", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="entity name required")
    return await api.forget(name)


@app.post("/api/link")
async def api_link(request: Request):
    _guard(request)
    body = await request.json()
    return await api.link(
        source=body["source"],
        target=body["target"],
        relation=body.get("relation", "related_to"),
        description=body.get("description", ""),
    )


@app.post("/api/forget_relationship")
async def api_forget_relationship(request: Request):
    _guard(request)
    body = await request.json()
    return await api.forget_relationship(
        source=body["source"],
        target=body["target"],
        relation=body["relation"],
    )


@app.post("/api/search")
async def api_search(request: Request):
    _guard(request)
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    return await api.search_memory(query, body.get("top_k", 8))


@app.get("/api/stats")
async def api_stats(request: Request):
    _guard(request)
    try:
        return await api.memory_stats()
    except Exception as ex:
        # Falls back gracefully when LightRAG/Ollama is offline
        return {"error": str(ex), "journal": jrn.stats()}


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    # Localhost-only; no additional auth on the socket
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()   # keepalive ping from client
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("WEB_UI_PORT", "5000"))
    print(f"Dashboard → http://localhost:{port}")
    if not WEB_UI_PASSWORD:
        print("  ⚠  WEB_UI_PASSWORD not set — running open (no auth)")
    uvicorn.run("dashboard:app", host="0.0.0.0", port=port, reload=False)
