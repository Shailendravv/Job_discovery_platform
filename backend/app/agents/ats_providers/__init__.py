"""ATS providers package — exports the registry and all providers."""
from app.agents.ats_providers.base import AtsProvider

# Import provider modules to trigger auto-registration via __init_subclass__
from app.agents.ats_providers import greenhouse  # noqa: F401
from app.agents.ats_providers import lever  # noqa: F401
from app.agents.ats_providers import ashby  # noqa: F401
from app.agents.ats_providers import workday  # noqa: F401

__all__ = [
    "AtsProvider",
]
