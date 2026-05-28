import httpx
from app.core.config import settings


def web_search(query: str, num_results: int = 10) -> list[dict]:
    """Search for jobs via SearXNG and return raw result items."""
    if not query:
        return []

    try:
        response = httpx.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": query.strip(), "format": "json", "count": num_results},
            timeout=10.0,
        )
        response.raise_for_status()
    except Exception:
        return []

    data = response.json()
    results = data.get("results", [])
    if not isinstance(results, list):
        return []

    return results[:num_results]
