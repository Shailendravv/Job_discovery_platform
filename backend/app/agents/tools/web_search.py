import threading

import httpx
from app.core.config import settings

# Persistent httpx client with cookie jar and realistic browser headers
_shared_client: httpx.Client | None = None
_client_lock: threading.Lock = threading.Lock()


def _get_client() -> httpx.Client:
    """Return a singleton httpx.Client with realistic browser headers and cookie persistence."""
    global _shared_client
    if _shared_client is None:
        with _client_lock:
            if _shared_client is None:
                _shared_client = httpx.Client(
                    cookies=httpx.Cookies(),
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "X-Forwarded-For": "127.0.0.1",
                        "X-Real-IP": "127.0.0.1",
                    },
                    timeout=15.0,
                )
    return _shared_client


def web_search(query: str, num_results: int = 10) -> list[dict]:
    """Search for jobs via SearXNG and return raw result items."""
    if not query:
        return []

    try:
        client = _get_client()
        response = client.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": query.strip(), "format": "json", "count": num_results},
        )
        response.raise_for_status()
    except Exception:
        return []

    data = response.json()
    results = data.get("results", [])
    if not isinstance(results, list):
        return []

    return results[:num_results]
