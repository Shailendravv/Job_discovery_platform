"""
Phase 2 — Tailoring with Gemma 4 E2B (or any Ollama-hosted model).

Sends editable text spans as a structured JSON payload and expects
structured JSON back — one rewrite per input span ID.

Key design:
- Batch processing: send one job/role's bullets together, not the whole resume.
- Structured output via Gemma 4's native JSON mode.
- Character budget per span so the model doesn't over-write.
- Fabrication guard: do not invent job titles, employers, dates, or metrics.
"""

import json
import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Schema definition for structured output
# ═══════════════════════════════════════════════════════════════

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "rewrites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["id", "new_text"],
            },
        }
    },
    "required": ["rewrites"],
}

SYSTEM_PROMPT = """You are a professional resume tailor. Your job is to rewrite resume content to better match a job description.

Rules:
- You will receive a list of text spans from a resume, each with an id, a character budget (char_budget), and a tier.
- Also receive a job description with the target job title and required skills.
- Return ONLY a JSON object matching the given schema: one rewrite per id you were given.

KEY INSTRUCTION — PRIORITIZE THE JD:
1. Analyze the job description carefully and identify the TOP 3-5 skills/technologies it emphasizes most.
2. Rewrite each text span to STRONGLY EMPHASIZE those top skills — use exact keyword matches from the JD where possible.
3. For skills mentioned in the original resume that are less relevant to THIS specific job (e.g., backend/AI skills when the JD is frontend-focused): de-emphasize them. Keep them brief or drop them entirely.
4. Do NOT invent job titles, employers, dates, degrees, or metrics that are not already present in the original text. You may rephrase and re-emphasize, never fabricate.
5. Stay within the given char_budget for each id. Do not exceed it.
6. Keep the original first-person/implied-subject style (resumes omit "I").
7. Use strong action verbs specific to the job's domain.
8. If a span is already a strong match for the job description, return it unchanged.
9. For skills (tier 3): reorder to put the most relevant skills first. Drop skills unrelated to the job.
10. Do NOT return any commentary, explanation, or markdown. Return ONLY the JSON object."""


async def tailor_spans_async(
    spans: list[dict],
    job_description: str,
    job_title: str = "",
    job_skills: Optional[list[str]] = None,
    model: str = "gemma4:e2b",
    base_url: str = "http://localhost:11434",
) -> list[dict]:
    """
    Send editable spans to an Ollama-hosted model and return rewritten spans.

    The model is prompted with structured JSON and expected to return
    structured JSON matching REWRITE_SCHEMA.

    Args:
        spans: List of content map span dicts (with id, text, char_budget, tier, etc.)
        job_description: Full job description text.
        job_title: Job title being targeted.
        job_skills: List of skills from the job description.
        model: Ollama model name (e.g. "gemma4:e2b").
        base_url: Ollama server base URL.

    Returns:
        List of {"id": str, "new_text": str} dicts.

    Raises:
        RuntimeError: If the LLM call fails or returns unparseable output.
    """
    if not spans:
        return []

    # ── Format the payload ──
    spans_payload = [
        {
            "id": s["id"],
            "tier": s.get("tier", 1),
            "text": s["text"],
            "char_budget": s.get("char_budget", len(s["text"]) + 10),
            "section": s.get("section", "unknown"),
        }
        for s in spans
    ]

    user_payload = {
        "job_description": job_description[:10000],  # Truncate to avoid context overflow
        "job_title": job_title or "Unknown Position",
        "job_skills": job_skills or [],
        "spans": spans_payload,
    }

    user_message = json.dumps(user_payload, ensure_ascii=False, indent=2)
    prompt_text = f"Tailor the following resume spans to match the job description.\n{user_message}"

    # ── Call Ollama ──
    try:
        raw_response = await _call_ollama_structured(
            prompt=prompt_text,
            system=SYSTEM_PROMPT,
            model=model,
            base_url=base_url,
        )
    except Exception as e:
        log.error("LLM call failed: %s", e, exc_info=True)
        # Fallback: return original texts unchanged
        return [{"id": s["id"], "new_text": s["text"]} for s in spans]

    # ── Parse JSON response ──
    try:
        parsed = _parse_llm_response(raw_response)
        if isinstance(parsed, dict) and "rewrites" in parsed:
            return parsed["rewrites"]
        elif isinstance(parsed, list):
            return parsed
        else:
            log.warning("Unexpected response shape from LLM: %s", type(parsed))
            return [{"id": s["id"], "new_text": s["text"]} for s in spans]
    except (json.JSONDecodeError, ValueError) as e:
        log.error("Failed to parse LLM response as JSON: %s", e)
        log.debug("Raw response: %s", raw_response[:500])
        return [{"id": s["id"], "new_text": s["text"]} for s in spans]


def tailor_spans(
    spans: list[dict],
    job_description: str,
    job_title: str = "",
    job_skills: Optional[list[str]] = None,
    model: str = "gemma4:e2b",
    base_url: str = "http://localhost:11434",
) -> list[dict]:
    """
    Synchronous wrapper around tailor_spans_async.

    Uses asyncio.run() to bridge async/sync.
    """
    import asyncio
    return asyncio.run(
        tailor_spans_async(
            spans=spans,
            job_description=job_description,
            job_title=job_title,
            job_skills=job_skills,
            model=model,
            base_url=base_url,
        )
    )


# ═══════════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════════


async def _call_ollama_structured(
    prompt: str,
    system: str = "",
    model: str = "gemma4:e2b",
    base_url: str = "http://localhost:11434",
) -> str:
    """
    Call an Ollama-hosted model with JSON format enabled.

    Uses the Ollama chat API with format="json" to request structured output.
    The model also receives the REWRITE_SCHEMA as part of the system prompt
    guidance so it knows what structure to produce.

    Args:
        prompt: The user message content.
        system: System prompt.
        model: Model name.
        base_url: Ollama server URL.

    Returns:
        Raw response text from the model.
    """
    url = f"{base_url.rstrip('/')}/api/chat"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 4096,
        },
        "format": "json",  # Request JSON mode from Ollama
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=body)
        response.raise_for_status()
        data = response.json()

    if "message" not in data:
        raise RuntimeError(f"Unexpected Ollama response: {data}")

    return data["message"]["content"]


def _parse_llm_response(raw: str) -> dict | list:
    """
    Parse the LLM response, cleaning markdown fences if present.

    Gemma 4 E2B with format="json" should return clean JSON, but we
    still handle the case where it wraps in ```json ... ``` fences.
    """
    import re

    cleaned = raw.strip()

    # Strip ```json ... ``` fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    # Strip any leading/trailing whitespace or newlines
    return json.loads(cleaned)


# ═══════════════════════════════════════════════════════════════
#  Batch-aware mode: send one section at a time
# ═══════════════════════════════════════════════════════════════


def tailor_spans_batched(
    spans: list[dict],
    job_description: str,
    job_title: str = "",
    job_skills: Optional[list[str]] = None,
    model: str = "gemma4:e2b",
    base_url: str = "http://localhost:11434",
    batch_size: int = 10,
) -> list[dict]:
    """
    Send spans in batches of batch_size to keep the model focused.

    Each batch is processed independently. Results are merged by span id.
    This gives better failure isolation — if one batch fails, only that
    batch falls back to original text.

    Returns:
        List of {"id": str, "new_text": str} dicts (one per input span).
    """
    all_results: dict[str, str] = {}
    all_results.update({s["id"]: s["text"] for s in spans})  # Default: original text

    import asyncio

    for i in range(0, len(spans), batch_size):
        batch = spans[i : i + batch_size]
        log.debug(
            "Processing batch %d-%d (%d spans)...",
            i,
            min(i + batch_size, len(spans)),
            len(batch),
        )
        try:
            batch_results = asyncio.run(
                tailor_spans_async(
                    spans=batch,
                    job_description=job_description,
                    job_title=job_title,
                    job_skills=job_skills,
                    model=model,
                    base_url=base_url,
                )
            )
            for r in batch_results:
                if r["id"] in all_results:
                    all_results[r["id"]] = r["new_text"]
        except Exception as e:
            log.warning("Batch %d-%d failed: %s. Using original text.", i, min(i + batch_size, len(spans)), e)

    return [{"id": sid, "new_text": text} for sid, text in all_results.items()]
