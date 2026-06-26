# Security Policy

## Posture: single-host proof of concept

Personal GraphRAG is a single-user, single-host project. By design it has **no
authentication on the MCP tunnel** — it assumes the server and the person using it
are the same trusted party on one machine. Treat it accordingly:

- **Do not expose the server publicly.** The `ngrok` tunnel is meant to reach your
  own machine from your own Claude.ai session. Anyone who learns the URL can read
  and write your memory graph. Keep the URL private and shut the tunnel down when
  you're not using it.
- **Your memory is personal data.** `data/memory_journal.jsonl` is the source of
  truth and is `.gitignore`d by default. Don't commit it to a public repo without
  reviewing what's in it.
- **The local model paths are optional.** `recall` / `extract_local` talk to a
  local Ollama instance; nothing leaves your machine except over the tunnel you
  open.

Authentication on the tunnel and a stable hostname are tracked as the top items on
the roadmap (see the README) and are required before any multi-user or
internet-facing use.

## Supported versions

This is a personal project under active development; only the latest `main` is
supported. There is no backport or LTS commitment.

| Version | Supported |
| ------- | --------- |
| `main` / latest release | Yes |
| older tags | No |

## Reporting a vulnerability

If you find a security issue, please report it privately rather than opening a
public issue:

- Preferred: open a [private security advisory](https://github.com/djuvinall/Personal-GraphRAG/security/advisories/new)
  on this repository.
- Or email the maintainer at djuvinall97@outlook.com.

Please include what you found, how to reproduce it, and the potential impact. As a
solo-maintained project, response is best-effort, but security reports are taken
seriously and prioritized.
