"""Abstract base class for ATS providers.

Every provider extends ``AtsProvider`` and registers automatically via
``AtsProvider.__init_subclass__``.  The registry lets the orchestrator
discover and iterate all providers without manual imports.
"""

from abc import ABC, abstractmethod
from typing import Optional


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
        order = ["greenhouse", "lever", "ashby", "workday"]
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
