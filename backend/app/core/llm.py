import logging
import threading
from app.core.config import settings

log = logging.getLogger(__name__)

from groq import Groq

_client_cache: dict[str, Groq] = {}


def _get_groq_client() -> Groq:
    """Get or create a cached Groq client."""
    if "groq" not in _client_cache:
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not configured in .env")
        _client_cache["groq"] = Groq(api_key=settings.GROQ_API_KEY)
    return _client_cache["groq"]


def call_llm(prompt: str, json_format: bool = False, timeout: int = 120, provider: str | None = None, max_tokens: int = 4096) -> str:
    """
    Call the configured LLM provider.
    Supports: ollama (default), groq.
    Pass provider= to override the configured default for specific use cases.
    """
    active_provider = (provider or getattr(settings, "LLM_PROVIDER", "ollama")).lower()

    if active_provider == "ollama":
        return _call_ollama(prompt, json_format, timeout)
    elif active_provider == "groq":
        return _call_groq(prompt, json_format, timeout, max_tokens)
    elif active_provider == "gemini":
        raise NotImplementedError("Gemini provider not fully implemented yet")
    else:
        raise ValueError(f"Unknown LLM provider: {active_provider}")


def _call_ollama(prompt: str, json_format: bool, timeout: int) -> str:
    import ollama

    client = ollama.Client(host=settings.Ollama)
    result = {}
    exc_box = []

    def _worker():
        try:
            options = {
                "temperature": settings.MODEL_TEMPERATURE,
                "num_predict": 1024
            }
            kwargs = {
                "model": settings.MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "options": options,
            }
            if json_format:
                kwargs["format"] = "json"

            try:
                kwargs["think"] = False
                resp = client.chat(**kwargs)
            except Exception:
                kwargs.pop("think")
                resp = client.chat(**kwargs)

            result["content"] = resp["message"]["content"]
        except Exception as e:
            exc_box.append(e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        raise RuntimeError(f"Ollama timeout after {timeout}s")
    if exc_box:
        raise exc_box[0]
    return result.get("content", "")


def _call_groq(prompt: str, json_format: bool, timeout: int, max_tokens: int = 4096) -> str:
    """Call Groq's LLM API."""
    client = _get_groq_client()

    model = settings.GROQ_MODEL_NAME
    messages = [{"role": "user", "content": prompt}]

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": settings.MODEL_TEMPERATURE,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }

    if json_format:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""
