# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Apache 2.0 `LICENSE` and `NOTICE`.
- `pyproject.toml` with project metadata, dependencies, and ruff config.
- GitHub Actions CI: lint + offline and integration tests on Python 3.10–3.12.
- Community docs: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, this changelog, and
  issue/PR templates.
- `docs/ARCHITECTURE.md` design-rationale document.

### Changed
- MCP server port is now configurable via `PMEM_PORT` (default `8000`), matching
  the documentation.
- Generalized references to the upstream MSP proof of concept.

### Fixed
- `.gitignore` no longer uses a backslash path for the Obsidian config; the whole
  `.obsidian/` directory is ignored and was removed from tracking.
- Corrected an off-by-one assertion in `test_integration.py` so the suite passes
  on a clean checkout.

## [0.1.0]

### Added
- Initial release: journal-first personal memory graph over LightRAG, with a
  FastMCP server exposing `remember` / `search_memory` and the graph primitives to
  Claude; pluggable `ollama`/`hash` embedding backends; deterministic
  journal-to-graph rebuild; offline and end-to-end test suites.
