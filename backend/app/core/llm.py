import logging
import threading
from app.core.config import settings

log = logging.getLogger(__name__)

def call_llm(prompt: str, json_format: bool = False, timeout: int = 120) -> str:
    """
    Call the configured LLM provider.
    Currently defaults to Ollama, but designed to be easily extensible for Groq/Gemini.
    """
    provider = getattr(settings, "LLM_PROVIDER", "ollama").lower()
    
    if provider == "ollama":
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
                
                # 'think=False' is specific to some models/versions, we can safely omit or try to include
                try:
                    kwargs["think"] = False
                    resp = client.chat(**kwargs)
                except Exception:
                    # Fallback if think=False is not supported by the client version
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
    
    elif provider == "groq":
        # Placeholder for Groq implementation
        # import groq
        # client = groq.Groq(api_key=settings.GROQ_API_KEY)
        raise NotImplementedError("Groq provider not fully implemented yet")
        
    elif provider == "gemini":
        # Placeholder for Gemini implementation
        # import google.generativeai as genai
        # genai.configure(api_key=settings.GEMINI_API_KEY)
        raise NotImplementedError("Gemini provider not fully implemented yet")
        
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
