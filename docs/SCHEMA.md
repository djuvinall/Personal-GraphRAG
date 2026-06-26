# SCHEMA — the personal-memory taxonomy

Three orthogonal axes describe every memory, so you can slice it any way you later
want to ask. All of this lives in `schema.py` (pure, no dependencies).

## 1. Entity types — *what kind of thing is this?*

A **closed** vocabulary (with aliases). Small and strong on purpose: a tight set
gives both Claude and the retriever a clear prior and keeps the graph legible.
Unknown/typo'd types fall back to `note` with a returned warning, so a write is
never lost.

| Type | Use it for |
|---|---|
| `person` | Friends, family, colleagues, collaborators, mentors, contacts. |
| `project` | Something you're building/driving — gamedev, homelab, an app, a repo. |
| `concept` | An idea, technique, pattern, or fact you want to keep. |
| `tool` | Software, hardware, language, framework, service, or device. |
| `task` | A concrete to-do / action item. |
| `goal` | A higher-level objective — what "done" looks like above a task. |
| `note` | A freeform thought, observation, journal entry, or decision record. |
| `preference` | How you like things — a like/dislike, a default, a way-of-working. |
| `resource` | An external reference — book, article, URL, video, course, doc. |
| `event` | A dated happening — meeting, milestone, release, trip. |
| `place` | A location, physical or virtual (a city, an office, a server, a Discord). |
| `organization` | A company, team, community, guild, or group. |
| `skill` | An ability you have or are building. |
| `habit` | A routine or recurring behavior. |

**Aliases** map casual input onto a real type (e.g. `game`/`app`/`repo` → `project`;
`book`/`url`/`video` → `resource`; `todo` → `task`; `company`/`team` →
`organization`). Full list in `schema.TYPE_ALIASES`.

## 2. Categories — *which area of life?*

Closed-**ish** life-domains. Validation **keeps** unknown categories (with a
warning) so the set grows naturally; bless a new one by adding it to
`schema.CATEGORIES`.

`gamedev` · `homelab` · `dev` · `work` · `learning` · `gaming` · `personal` ·
`health` · `finance` · `social` · `creative` · `ideas`

Categories let you `browse(category="homelab")` or ask "everything in gamedev".

## 3. Tags — *everything else*

Free-form, many per entity, normalized to lower-`kebab-case` and de-duplicated
(`"Godot, godot #shader"` → `["godot", "shader"]`). This is the flexible layer for
cross-cutting facets that types and categories don't capture (`active`, `someday`,
`urgent`, `oss`, a game's name, a client's name, …).

## Relations — the edges

Relationships are how memory becomes a *graph* instead of a list. **Claude supplies
them directly** (no model infers them). The vocabulary below is recommended for
consistency, but any relation string is accepted (it's stored in the edge's
`keywords`).

| Relation | Typical shape |
|---|---|
| `works_on` | person → project |
| `created_by` | thing → person |
| `uses` | project/person → tool |
| `part_of` | thing → larger thing |
| `depends_on` | thing → prerequisite |
| `blocks` | task/issue → thing it holds up |
| `knows` | person → person |
| `member_of` | person → organization |
| `learned_from` | concept/skill → resource/person |
| `interested_in` | you/person → concept |
| `prefers` | you → preference |
| `located_at` | thing/event → place |
| `attended` | person → event |
| `owns` | person → tool/resource |
| `references` | note/resource → thing |
| `inspired_by` | idea/project → source |
| `next_step` | goal → task |
| `about` / `mentions` | note → entity |
| `related_to` | generic fallback |

## How metadata is stored (and why it's searchable)

Each entity's `type`, `category`, and `tags` are **baked into the text** that gets
embedded, e.g.:

```
Shader Atlas — Tool that bakes material variants into a texture atlas for Godot.
  [type: project; category: gamedev; tags: godot, rendering, active]
```

So a semantic search for "godot rendering" can surface the node even if those words
aren't in the prose. The **structured** values also live in the journal, which is
the authoritative copy `rebuild.py` reads.

## Design notes

- **Names are identity.** An entity is keyed by its `name` (case-insensitively).
  Re-using a name merges; vary it and you get two nodes. Keep names canonical.
- **Closed types, open everything else.** Types are the one place we're strict,
  because mistyped nodes are what made the MSP PoC's LLM graph hard to use.
- **Edit by re-stating.** There's no `update` verb — `remember` the entity again
  with new details and it merges (tags union, newest description/type win).
