# Contributing

Thanks for your interest. This is a single-maintainer personal project, but issues
and pull requests are welcome.

## Getting set up

```bash
python -m venv venv
. venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"      # optional: editable install + ruff
```

No Ollama required for development — set `PMEM_EMBED_BACKEND=hash` and the whole
system (and the test suite) runs with the zero-dependency embedder.

## Running the tests

```bash
python test_memory.py        # pure, offline core logic (no LightRAG, no Ollama)
PMEM_EMBED_BACKEND=hash python test_integration.py   # end-to-end on the hash backend
```

Both must pass before a PR is merged. CI runs them on Python 3.10–3.12.

## Linting

CI runs `ruff check .` with a deliberately small rule set (`E9, F63, F7, F82`) —
real bugs only (syntax errors, undefined names, broken comparisons), not style.
Please don't reformat existing code to a different style in a feature PR.

## Design constraints (please preserve these)

A few invariants define this project. Changes that break them will be declined:

- **Claude is the relationship model.** The `remember` write path is deterministic:
  entities and edges come from structured input, never from a second extraction
  model. Don't add LLM extraction to the main write path. Local extraction stays
  optional and review-first in `extract_local.py`.
- **Journal-first.** Every write appends to `data/memory_journal.jsonl` before the
  graph is touched. The graph is a derived, disposable index; `rebuild.py` must stay
  able to reconstruct it losslessly from the journal.
- **The read path needs no LLM.** `search_memory` and the graph primitives return
  raw context with no model in the loop.
- **Closed entity types.** New types go in `schema.ENTITY_TYPES` with an alias, not
  as free-form strings.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the reasoning behind these.

## Pull requests

1. Keep changes focused; one concern per PR.
2. Add or update a test when you change behavior.
3. Update `CLAUDE.md` / `docs/` if you change how something works.
4. Note user-facing changes in `CHANGELOG.md` under "Unreleased".

## Reporting bugs

Open an issue with what you expected, what happened, your OS/Python version, and
which embedding backend you were on (`ollama` or `hash`).
