"""``AtsProvider.get_providers()`` uses a hardcoded ``order`` list (base.py)
separate from the ``__init_subclass__`` auto-registration — a provider that
registers but is missing from ``order`` is silently never instantiated, so
``registry.resolve_sources()`` would never match it even though
``AtsProvider._registry`` has it. This is a real gap the code-review-graph's
static ``tests_for`` check can't see (dispatch-based registration isn't
statically traced), so it's covered directly here instead.
"""

from app.agents.ats_providers import AtsProvider

EXPECTED_IDS = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "workday"}


def test_get_providers_includes_every_registered_provider():
    """Every provider module imported by app/agents/ats_providers/__init__.py
    must also appear in get_providers()'s order list, or it's dead code."""
    registered_ids = set(AtsProvider._registry.keys())
    instantiated_ids = {p.id for p in AtsProvider.get_providers()}
    assert instantiated_ids == registered_ids, (
        f"registered but never instantiated: {registered_ids - instantiated_ids} — "
        f"add these to the `order` list in base.py's get_providers()"
    )


def test_get_providers_includes_all_milestone_5_ids():
    ids = {p.id for p in AtsProvider.get_providers()}
    assert EXPECTED_IDS <= ids
