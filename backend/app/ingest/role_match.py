"""Deterministic role/title matching for the Job Discovery search box.

No LLM, no embeddings, no fuzzy scoring — a role query becomes a regex over
``title_normalized`` and Mongo does the rest. The one piece of "knowledge"
here is a hand-written synonym table, which is data, not inference: a user
who types "backend engineer" expects "Back-End Developer" back, and that
mapping is stable enough to hard-code.

Why ``title_normalized`` and not ``title``: normalize.py already wrote the
lowercased, whitespace-collapsed form of every title at ingest time
(``models.normalize_text_key``), so matching against it needs no
case-insensitivity flag — and a plain ``$regex`` without ``$options: "i"``
can actually use an index.
"""

import re
from typing import Optional

from app.ingest.models import normalize_text_key

# Words that carry no signal in a job title and would otherwise force a
# match on filler ("engineer for the platform team" -> "for", "the").
_STOPWORDS = frozenset({
    "a", "an", "and", "at", "for", "in", "of", "on", "or", "the", "to", "with",
    "job", "jobs", "role", "roles", "position", "positions", "opening", "openings",
})

# Hand-maintained equivalence classes. Each entry maps a token to the full
# set of surface forms that should satisfy it. Deliberately conservative —
# a wrong synonym silently widens every search that uses that word.
#
# Multi-word forms are included as alternatives (e.g. "machine learning" for
# "ml"); the pattern builder escapes them and allows the space.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "engineer": ("engineer", "developer", "dev"),
    "developer": ("developer", "engineer", "dev"),
    "dev": ("dev", "developer", "engineer"),
    "senior": ("senior", "sr"),
    "sr": ("sr", "senior"),
    "junior": ("junior", "jr"),
    "jr": ("jr", "junior"),
    "frontend": ("frontend", "front-end", "front end"),
    "backend": ("backend", "back-end", "back end"),
    "fullstack": ("fullstack", "full-stack", "full stack"),
    "ml": ("ml", "machine learning"),
    "ai": ("ai", "artificial intelligence"),
    "sde": ("sde", "software engineer", "software development engineer"),
    "sre": ("sre", "site reliability"),
    "devops": ("devops", "dev ops", "platform"),
    "qa": ("qa", "quality assurance", "sdet"),
}

# Multi-word phrases folded to a single canonical token *before* the query is
# tokenized. Without this the synonym table only works one way: "ml engineer"
# would find "Machine Learning Engineer" (because the token "ml" expands to
# include that phrase), but "machine learning engineer" would not find "ML
# Engineer" — the query would have split into two tokens neither of which
# appears in the title. Folding first makes both directions work through the
# one table.
#
# Only unambiguous phrases belong here. "software engineer" deliberately does
# *not* fold to "sde": leaving it as two tokens lets "engineer" expand to
# developer, so the query still finds "Software Developer".
_PHRASES: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern), canonical)
    for pattern, canonical in (
        (r"\bmachine[\s-]+learning\b", "ml"),
        (r"\bartificial[\s-]+intelligence\b", "ai"),
        (r"\bfront[\s-]+end\b", "frontend"),
        (r"\bback[\s-]+end\b", "backend"),
        (r"\bfull[\s-]+stack\b", "fullstack"),
        (r"\bsite[\s-]+reliability\b", "sre"),
        (r"\bquality[\s-]+assurance\b", "qa"),
        (r"\bdev[\s-]+ops\b", "devops"),
    )
)

# Split on anything that isn't a letter, digit, +, or # — so "c++", "c#" and
# ".net" survive as tokens while "/", ",", "-" and "()" act as separators.
_TOKEN_SPLIT = re.compile(r"[^a-z0-9+#.]+")


def _canonicalize_phrases(text: str) -> str:
    for pattern, canonical in _PHRASES:
        text = pattern.sub(canonical, text)
    return text


def parse_role_query(query: Optional[str]) -> list[str]:
    """Break a user's role query into the tokens a title must contain.

    Normalized the same way titles were at ingest time, multi-word phrases
    folded, stopwords dropped, order-independent, duplicates collapsed.
    Returns ``[]`` for an empty or all-stopword query, which callers treat as
    "no role filter".
    """
    if not query:
        return []

    tokens: list[str] = []
    for token in _TOKEN_SPLIT.split(_canonicalize_phrases(normalize_text_key(query))):
        token = token.strip(".")
        if not token or token in _STOPWORDS or token in tokens:
            continue
        tokens.append(token)
    return tokens


def _alternatives_pattern(token: str) -> str:
    """Regex fragment matching ``token`` or any of its synonyms, as a whole
    word. ``\\b`` works on the ``-``/space boundaries in the multi-word forms
    too, since those are non-word characters."""
    forms = _SYNONYMS.get(token, (token,))
    alternatives = "|".join(re.escape(form) for form in forms)
    return rf"(?=.*\b(?:{alternatives})\b)"


def build_title_pattern(tokens: list[str]) -> Optional[str]:
    """A single regex requiring **every** token (or one of its synonyms) to
    appear somewhere in the title, in any order.

    Implemented as a chain of lookaheads so the tokens stay order-independent
    — "engineer backend" and "backend engineer" match the same postings —
    without needing one regex per token.
    """
    if not tokens:
        return None
    return "".join(_alternatives_pattern(token) for token in tokens)


def build_title_query(query: Optional[str]) -> Optional[dict]:
    """The Mongo clause for a role query, or ``None`` when there is nothing
    to filter on. Ready to drop straight into a ``postings`` find filter as
    the value of ``title_normalized``."""
    pattern = build_title_pattern(parse_role_query(query))
    return {"$regex": pattern} if pattern else None


def title_matches(title: str, query: Optional[str]) -> bool:
    """The same rule applied in Python, for tests and for any caller holding
    postings in memory rather than querying. Kept next to the query builder
    so the two can never drift."""
    pattern = build_title_pattern(parse_role_query(query))
    if pattern is None:
        return True
    return re.search(pattern, normalize_text_key(title)) is not None


def relaxation_ladder(query: Optional[str]) -> list[list[str]]:
    """Progressively broader token sets for one role query, strictest first.

    ``build_title_query`` requires *every* token, which is the right default
    but narrows multiplicatively: each qualifier a user adds cuts the result
    set again. "AI full stack developer" matched 17 titles out of a
    23k-posting corpus, and none of the 17 were inside the freshness window
    — so the Discovery page reported "0 matches" while the corpus held
    perfectly good full-stack roles. Zero results for a reasonable query is
    a worse answer than slightly-too-broad ones, provided the caller says
    what it broadened to.

    Tokens are given up left to right because an English job title puts the
    head noun last — "Senior AI Full Stack **Developer**". Shedding from the
    left drops seniority and domain qualifiers while keeping the role
    itself; the opposite order would relax towards "ai fullstack", which is
    not a job anyone posts. This is a property of the language, not a
    hand-maintained table, so it needs no upkeep as new domains appear.

    The last rung is always a single token, never ``[]``: relaxing to an
    empty filter would turn a role search into "show me everything", which
    misleads more than showing nothing. An empty query is the one exception
    — it yields ``[[]]``, meaning "no role filter", which callers must not
    report as relaxation.
    """
    tokens = parse_role_query(query)
    if not tokens:
        return [[]]
    return [tokens[i:] for i in range(len(tokens))]
