"""Role search is deterministic: tokenize, expand a fixed synonym table,
require every token. No LLM, no fuzzy scoring, no ranking."""

import re

import pytest

from app.ingest.models import normalize_text_key
from app.ingest.role_match import (
    build_title_pattern,
    build_title_query,
    parse_role_query,
    title_matches,
)


# ---- parse_role_query -------------------------------------------------

def test_tokenizes_and_normalizes():
    assert parse_role_query("Senior Backend Engineer") == ["senior", "backend", "engineer"]


def test_drops_stopwords():
    assert parse_role_query("engineer for the platform team") == ["engineer", "platform", "team"]


def test_collapses_duplicates():
    assert parse_role_query("engineer engineer") == ["engineer"]


def test_splits_on_punctuation():
    """Slashes separate words. "front-end"/"back-end" survive as single
    tokens because phrase folding runs before the split -- otherwise both
    would shatter into a shared, meaningless "end" token."""
    assert parse_role_query("front-end / back-end developer") == [
        "frontend", "backend", "developer",
    ]


def test_folds_multi_word_phrases_before_tokenizing():
    """Without this, the synonym table only works one way: "ml engineer"
    would find "Machine Learning Engineer", but not the reverse."""
    assert parse_role_query("machine learning engineer") == ["ml", "engineer"]
    assert parse_role_query("site reliability engineer") == ["sre", "engineer"]


def test_keeps_language_names_that_contain_symbols():
    """"c++", "c#" and ".net" are real title tokens -- splitting on every
    non-alphanumeric would destroy them."""
    assert "c++" in parse_role_query("C++ Engineer")
    assert "c#" in parse_role_query("C# Developer")
    assert "net" in parse_role_query(".NET Engineer")


def test_empty_query_yields_no_tokens():
    assert parse_role_query("") == []
    assert parse_role_query(None) == []


def test_all_stopword_query_yields_no_tokens():
    assert parse_role_query("the role for a position") == []


# ---- build_title_pattern ----------------------------------------------

def test_no_tokens_means_no_pattern():
    """An empty or all-stopword query is "no role filter", not "match
    nothing" -- the difference between showing everything and showing zero."""
    assert build_title_pattern([]) is None
    assert build_title_query("") is None
    assert build_title_query("the a of") is None


def test_query_clause_shape_is_index_friendly():
    """title_normalized was already lowercased at ingest time, so the clause
    needs no $options: "i" -- and a regex without it can use an index."""
    clause = build_title_query("backend engineer")
    assert set(clause) == {"$regex"}


# ---- title_matches ----------------------------------------------------

@pytest.mark.parametrize("title", [
    "Backend Engineer",
    "Back-End Engineer",
    "Back End Developer",
    "Senior Backend Developer",
    "Backend Software Engineer (Remote)",
])
def test_matches_expected_titles(title):
    assert title_matches(title, "backend engineer")


@pytest.mark.parametrize("title", [
    "Frontend Engineer",
    "Data Scientist",
    "Backend Product Manager",   # "backend" but no engineer/developer/dev
    "Engineering Manager",
])
def test_rejects_unrelated_titles(title):
    assert not title_matches(title, "backend engineer")


def test_token_order_does_not_matter():
    assert title_matches("Engineer, Backend Platform", "backend engineer")
    assert title_matches("Backend Engineer", "engineer backend")


def test_every_token_must_be_present():
    """Tokens are ANDed. A title matching only half the query is not a
    match, which is what keeps a 200-company sweep from returning noise."""
    assert not title_matches("Backend Engineer", "senior backend engineer")
    assert title_matches("Senior Backend Engineer", "senior backend engineer")


def test_synonyms_expand_both_directions():
    assert title_matches("Software Developer", "software engineer")
    assert title_matches("Sr. Software Engineer", "senior software engineer")
    assert title_matches("ML Engineer", "machine learning engineer")
    assert title_matches("Machine Learning Engineer", "ml engineer")


def test_matches_are_whole_word():
    """Substring matching would make "dev" match "device" and "ai" match
    "maintain" -- the classic way a keyword filter turns into noise."""
    assert not title_matches("Device Firmware Specialist", "dev")
    assert not title_matches("Maintenance Technician", "ai")


def test_empty_query_matches_everything():
    assert title_matches("Anything At All", "")
    assert title_matches("Anything At All", None)


def test_python_and_mongo_paths_agree():
    """title_matches() and build_title_query() must stay in step -- one is
    used in tests and in-memory, the other by Mongo."""
    query, title = "senior backend engineer", "Senior Back-End Developer"
    pattern = build_title_query(query)["$regex"]
    assert bool(re.search(pattern, normalize_text_key(title))) is title_matches(title, query)
