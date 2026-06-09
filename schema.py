"""
schema.py — the personal-memory taxonomy.

Three orthogonal axes, so a memory can be sliced any way you later want to ask
about it:

  1. ENTITY TYPE   — *what kind of thing* this node is (closed vocabulary).
  2. CATEGORY      — *which area of life* it belongs to (a life-domain; closed-ish,
                     but unknown values are allowed with a warning).
  3. TAGS          — *anything else*, freeform, many per entity (the flexible layer).

Plus a recommended RELATION vocabulary for edges. Claude supplies relationships
directly (no extraction model), so this is a *suggested* set to keep edges
consistent — unknown relations are allowed.

This module is pure stdlib and import-safe (no lightrag / ollama / numpy), so the
builder and tests can validate against it without spinning anything up.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. ENTITY TYPES — what kind of thing is this node?
#    Closed vocabulary. A small, strong set beats a sprawling one: it gives both
#    Claude and the retriever a clear prior and keeps the graph legible. Tuned
#    for a builder/IT/gamedev/systems person who also has a life.
# ---------------------------------------------------------------------------
ENTITY_TYPES: dict[str, str] = {
    "person":       "A human — friend, family, colleague, collaborator, mentor, contact.",
    "project":      "Something you're building or driving — gamedev, homelab, app, side project, repo.",
    "concept":      "An idea, technique, pattern, or piece of knowledge you want to remember.",
    "tool":         "Software, hardware, language, framework, service, or device you use.",
    "task":         "A concrete to-do / action item. Has a doneness; lives until closed.",
    "goal":         "An objective or aspiration — what 'done' looks like at a higher level than a task.",
    "note":         "A freeform thought, observation, journal entry, or decision record.",
    "preference":   "How you like things — a like/dislike, a default, a way-of-working. Powers personalization.",
    "resource":     "An external reference — book, article, URL, video, course, doc, repo to read.",
    "event":        "A dated happening — meeting, milestone, release, trip, appointment.",
    "place":        "A location — physical or virtual (a city, an office, a server, a Discord).",
    "organization": "A company, team, community, guild, or group.",
    "skill":        "An ability you have or are deliberately building.",
    "habit":        "A routine or recurring behavior you want to track or reinforce.",
}

# ---------------------------------------------------------------------------
# 2. CATEGORIES — which area of life? (life-domains)
#    Closed-ish: validation WARNS on unknown values but never rejects, so you can
#    grow this list naturally. Lets you ask "show me everything in homelab".
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, str] = {
    "gamedev":   "Game development — engines, design, art, your game projects.",
    "homelab":   "Self-hosting, servers, networking, infra, this GraphRAG itself.",
    "dev":       "General software engineering / coding not tied to a game.",
    "work":      "Job / career / clients / professional.",
    "learning":  "Studying, courses, things you're actively learning.",
    "gaming":    "Playing games — backlog, sessions, communities.",
    "personal":  "Life admin, home, errands, misc personal.",
    "health":    "Fitness, sleep, food, medical, wellbeing.",
    "finance":   "Money, budget, purchases, subscriptions.",
    "social":    "Friends, family, relationships, events with people.",
    "creative":  "Writing, music, art, making things outside of code.",
    "ideas":     "Raw ideas / someday-maybe / things to explore.",
}

# ---------------------------------------------------------------------------
# 3. RELATIONS — recommended edge vocabulary (Claude provides edges; unknown OK).
#    Stored in the edge `keywords` field. Kept human-readable on purpose.
# ---------------------------------------------------------------------------
RELATIONS: dict[str, str] = {
    "works_on":     "person/you -> project  (active involvement).",
    "created_by":   "thing -> person  (authorship / origin).",
    "uses":         "project/person -> tool  (depends on / built with).",
    "part_of":      "thing -> larger thing  (membership / containment).",
    "depends_on":   "thing -> thing it requires.",
    "blocks":       "task/issue -> thing it is holding up.",
    "related_to":   "generic association when nothing more specific fits.",
    "knows":        "person -> person.",
    "member_of":    "person -> organization / community.",
    "learned_from": "concept/skill -> resource/person it came from.",
    "interested_in":"you/person -> concept/topic.",
    "prefers":      "you -> preference / option chosen.",
    "located_at":   "thing/event -> place.",
    "attended":     "person -> event.",
    "owns":         "person -> tool/device/resource.",
    "references":   "note/resource -> thing it points at.",
    "inspired_by":  "idea/project -> source of inspiration.",
    "next_step":    "goal -> task that advances it.",
    "about":        "note/event -> the entity it concerns.",
    "mentions":     "note -> entity named in it.",
}

# Default fallbacks used when a caller omits a field.
DEFAULT_TYPE     = "note"
DEFAULT_CATEGORY = "personal"
DEFAULT_RELATION = "related_to"

# A handful of obvious aliases so casual input still lands on a real type, rather
# than silently becoming a generic note. Extend freely.
TYPE_ALIASES: dict[str, str] = {
    "people": "person", "human": "person", "contact": "person", "friend": "person",
    "repo": "project", "app": "project", "game": "project",
    "idea": "concept", "topic": "concept", "knowledge": "concept",
    "software": "tool", "framework": "tool", "language": "tool", "device": "tool",
    "service": "tool", "hardware": "tool",
    "todo": "task", "action": "task", "action_item": "task",
    "objective": "goal", "aspiration": "goal",
    "journal": "note", "thought": "note", "decision": "note", "observation": "note",
    "like": "preference", "dislike": "preference", "setting": "preference",
    "book": "resource", "article": "resource", "url": "resource", "link": "resource",
    "video": "resource", "course": "resource", "doc": "resource", "paper": "resource",
    "meeting": "event", "milestone": "event", "release": "event", "trip": "event",
    "location": "place", "city": "place", "server": "place",
    "company": "organization", "team": "organization", "community": "organization",
    "group": "organization", "guild": "organization",
    "ability": "skill",
    "routine": "habit",
}


def normalize_type(t: str | None) -> tuple[str, str | None]:
    """Map a raw type string to a canonical ENTITY_TYPE.

    Returns (canonical_type, warning_or_None). Never raises — unknown types fall
    back to DEFAULT_TYPE with a warning so a write is never lost over a typo.
    """
    if not t:
        return DEFAULT_TYPE, None
    key = t.strip().lower().replace(" ", "_")
    if key in ENTITY_TYPES:
        return key, None
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key], None
    return DEFAULT_TYPE, f"unknown entity_type {t!r} -> defaulted to {DEFAULT_TYPE!r}"


def normalize_category(c: str | None) -> tuple[str, str | None]:
    """Map a raw category to a known life-domain. Unknown values are KEPT (lower-
    cased) with a warning — categories are meant to grow."""
    if not c:
        return DEFAULT_CATEGORY, None
    key = c.strip().lower().replace(" ", "_")
    if key in CATEGORIES:
        return key, None
    return key, f"unknown category {c!r} (kept; add it to schema.CATEGORIES to bless it)"


def normalize_tags(tags) -> list[str]:
    """Normalize tags to a clean, de-duplicated, lower-kebab list."""
    if not tags:
        return []
    if isinstance(tags, str):
        tags = [t for t in tags.replace(",", " ").split()]
    out, seen = [], set()
    for t in tags:
        s = str(t).strip().lower().replace(" ", "-").lstrip("#")
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def normalize_relation(r: str | None) -> str:
    """Relations are freeform; we just clean them. Unknown relations are fine."""
    if not r:
        return DEFAULT_RELATION
    return r.strip().lower().replace(" ", "_")


def valid_types() -> set[str]:
    return set(ENTITY_TYPES)
