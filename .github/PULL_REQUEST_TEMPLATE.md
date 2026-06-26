<!-- Thanks for contributing! Keep PRs focused on one concern. -->

## What this changes

<!-- A short summary of the change and why. -->

## Type

- [ ] Bug fix
- [ ] New feature
- [ ] Docs
- [ ] Refactor / internal

## Checklist

- [ ] `python test_memory.py` passes
- [ ] `PMEM_EMBED_BACKEND=hash python test_integration.py` passes
- [ ] Added/updated a test for the behavior change (if applicable)
- [ ] Updated `CLAUDE.md` / `docs/` if behavior changed
- [ ] Added a `CHANGELOG.md` entry under "Unreleased" (if user-facing)
- [ ] Preserves the design constraints in `CONTRIBUTING.md` (journal-first,
      deterministic write path, no-LLM read path)
