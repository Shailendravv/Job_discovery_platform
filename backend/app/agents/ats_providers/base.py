"""Abstract base class for ATS providers.

Every provider extends ``AtsProvider`` and registers automatically via
``AtsProvider.__init_subclass__``.  The registry lets the orchestrator
discover and iterate all providers without manual imports.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional, TypedDict


class RawPosting(TypedDict, total=False):
    """Full-fidelity posting returned by ``fetch_postings()``.

    Distinct from the lossy dict returned by the legacy ``fetch()`` (which
    only carries what the dashboard search UI needs). This is the shape the
    ingestion pipeline (``backend/app/ingest/``) normalizes into a ``Posting``.
    """

    provider_job_id: str
    title: str
    location: Optional[str]
    remote_flag: Optional[bool]
    employment_type: Optional[str]
    description_text: str
    salary: Optional[str]
    url: str
    apply_url: Optional[str]
    posted_at: Optional[datetime]
    raw: dict[str, Any]


class AtsProvider(ABC):
    """Base class for all ATS job providers.

    Subclasses must set ``id`` as a class-level attribute and implement
    ``detect()`` and ``fetch()``.  Registration is automatic.
    """

    id: str = ""  # Set by subclass, e.g. "greenhouse", "ashby", "lever", "workday"

    # ── Registry ────────────────────────────────────────────────────────
    _registry: dict[str, type["AtsProvider"]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Auto-register every concrete subclass."""
        super().__init_subclass__(**kwargs)
        if cls.id:
            AtsProvider._registry[cls.id] = cls

    @classmethod
    def get_providers(cls) -> list["AtsProvider"]:
        """Instantiate and return all registered providers in a fixed order."""
        # PLAN.md milestone 5 added workable/smartrecruiters/recruitee; workday
        # stays last — it's the messiest connector (paginated POST + a second
        # per-job call for the description) and was built last per PLAN.md §2.
        order = ["greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "workday"]
        instances: list[AtsProvider] = []
        for pid in order:
            klass = cls._registry.get(pid)
            if klass:
                instances.append(klass())
        return instances

    # ── Contract ────────────────────────────────────────────────────────

    @abstractmethod
    def detect(self, company: dict) -> Optional[str]:
        """Match company config to this provider via URL pattern.

        Parameters
        ----------
        company : dict
            A single entry from ``ats_companies.yml`` with at least
            a ``careers_url`` key.

        Returns
        -------
        str or None
            The API URL to fetch jobs from, or ``None`` if this provider
            cannot handle the company.
        """
        ...

    @abstractmethod
    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        """Fetch jobs from the ATS API and return normalised job dicts.

        Each job dict should have the keys expected by ``JobResult``
        (title, company, location, url, posted_date, salary, description).

        Parameters
        ----------
        company : dict
            Company config entry.
        api_url : str
            The API URL returned by ``detect()``.

        Returns
        -------
        list[dict]
            Normalised job listings.
        """
        ...

    # ── Ingestion contract (optional) ──────────────────────────────────
    # Separate from ``fetch()`` so the existing dashboard search path
    # (which calls ``fetch()``) cannot regress when a provider gains
    # ingestion support. All seven providers implement this as of
    # milestone 5 (Workday was last); a future provider that doesn't yet
    # is reported by the ingest runner as "not_ingestable" rather than
    # crashing the run — see runner.py's ``_fetch_source()``.

    async def fetch_postings(self, company: dict, api_url: str) -> list[RawPosting]:
        """Fetch jobs with full fidelity for the ingestion store.

        Unlike ``fetch()``, this must include a stable ``provider_job_id``,
        the full ``description_text``, and the ``raw`` source payload so the
        ingest layer can compute a deterministic id and a debuggable record.

        Parameters
        ----------
        company : dict
            Company config entry.
        api_url : str
            The API URL returned by ``detect()``.

        Returns
        -------
        list[RawPosting]

        Raises
        ------
        NotImplementedError
            If this provider does not yet support ingestion.
        """
        raise NotImplementedError(f"{self.id or type(self).__name__}: fetch_postings() not implemented")
