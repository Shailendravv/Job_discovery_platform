"""Registry resolution — no network (``detect()`` is offline regex matching
against the ``careers_url``, unlike ``fetch()``/``fetch_postings()``).

This is the guard against dead registry entries accumulating as
``ats_companies.yml`` grows past 150+ orgs (PLAN.md milestone 5)."""

from app.ingest.registry import load_and_resolve_sources, load_sources


def test_registry_loads_at_least_one_source():
    sources = load_sources()
    assert len(sources) > 0


def test_every_enabled_entry_resolves_to_a_provider():
    sources = load_and_resolve_sources()
    unresolved = [s for s in sources if s.enabled and not s.provider_id]
    assert unresolved == [], (
        f"{len(unresolved)} enabled registry entries matched no provider: "
        f"{[s.name for s in unresolved]}"
    )


def test_no_two_enabled_entries_resolve_to_the_same_endpoint():
    """Two registry rows resolving to the same (provider, api_url) waste an
    HTTP call and double-count postings_fetched for zero benefit — caught
    once already during registry expansion (Amplitude/GitLab/Reddit/Airbnb/
    Lyft each had a stray second entry with a different careers_url pattern
    pointing at the identical API endpoint)."""
    sources = load_and_resolve_sources()
    seen: dict[tuple[str, str], str] = {}
    collisions = []
    for s in sources:
        if not s.enabled or not s.provider_id:
            continue
        key = (s.provider_id, s.api_url)
        if key in seen:
            collisions.append((s.name, seen[key]))
        else:
            seen[key] = s.name
    assert collisions == [], f"duplicate resolved endpoints: {collisions}"


def test_disabled_entries_are_not_silently_dropped():
    """Disabled entries (e.g. a dead token caught by `sources doctor`)
    should still load — just flagged — not disappear from the registry."""
    sources = load_sources()
    disabled = [s for s in sources if not s.enabled]
    # This registry has at least one known-disabled entry (Vellum, caught
    # by doctor on 2026-09-07). If this ever fails because it was re-enabled
    # or removed, that's fine — update this test to match.
    assert any(s.name == "Vellum" for s in disabled)
