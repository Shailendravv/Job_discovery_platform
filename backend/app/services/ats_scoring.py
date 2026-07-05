"""
ATS Scoring — project ranking, bullet reordering, keyword coverage.

All operations run AFTER the LLM returns tailored data, so they can
slice/reorder without affecting the LLM's output integrity.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


def rank_projects_by_jd(
    projects: list[dict],
    jd_keywords: list[str],
    max_projects: int = 999,
) -> list[dict]:
    """
    Rank projects by JD keyword overlap and keep top *max_projects*.

    Each project gets a relevance score = number of unique JD keywords
    found in its name + description. Default max is 999 to preserve all projects.
    """
    if not projects or not jd_keywords:
        return projects[:max_projects] if max_projects else projects

    kw_lower = [k.lower() for k in jd_keywords]
    scored = []
    for proj in projects:
        text = f"{proj.get('name', '')} {proj.get('description', '')}".lower()
        matched = sum(1 for kw in kw_lower if kw in text)
        scored.append((matched, proj))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [proj for _, proj in scored][:max_projects]

    log.info("Ranked %d projects → keeping top %d by JD relevance", len(projects), len(ranked))
    return ranked


def reorder_bullets_by_jd(
    experience: list[dict],
    jd_keywords: list[str],
) -> list[dict]:
    """
    Within each experience entry, sort bullet points so JD-relevant ones appear first.
    """
    if not experience or not jd_keywords:
        return experience

    kw_lower = [k.lower() for k in jd_keywords]
    for exp in experience:
        desc = exp.get("description", "")
        if not desc:
            continue
        bullets = [b.strip() for b in desc.split("\n") if b.strip()]
        if len(bullets) <= 1:
            continue
        scored = []
        for bullet in bullets:
            bullet_clean = bullet.lstrip("-•*").strip().lower()
            matched = sum(1 for kw in kw_lower if kw in bullet_clean)
            scored.append((matched, bullet))
        scored.sort(key=lambda x: x[0], reverse=True)
        exp["description"] = "\n".join(b for _, b in scored)

    log.debug("Reordered bullets for %d experience entries", len(experience))
    return experience


def compute_keyword_coverage(
    tailored_data: dict,
    jd_keywords: list[str],
) -> dict:
    """
    Compute keyword coverage metrics for the tailored resume.

    Returns dict with:
        matched: list[str]
        missing: list[str]
        coverage_pct: float
        distribution: dict[str, list[str]]
    """
    if not jd_keywords:
        return {"matched": [], "missing": [], "coverage_pct": 0.0, "distribution": {}}

    kw_lower = {k.lower(): k for k in jd_keywords}
    matched: set[str] = set()
    distribution: dict[str, list[str]] = {
        "summary": [], "experience": [], "skills": [], "projects": [],
    }

    # Summary
    summary = (tailored_data.get("summary") or "").lower()
    for kw_low, original in kw_lower.items():
        if kw_low in summary:
            matched.add(original)
            distribution["summary"].append(original)

    # Experience
    for exp in tailored_data.get("experience", []):
        exp_text = f"{exp.get('company', '')} {exp.get('title', '')} {exp.get('description', '')}".lower()
        for kw_low, original in kw_lower.items():
            if kw_low in exp_text and original not in distribution["experience"]:
                matched.add(original)
                distribution["experience"].append(original)

    # Skills
    for skill in tailored_data.get("skills", []):
        skill_lower = skill.lower()
        for kw_low, original in kw_lower.items():
            if kw_low == skill_lower or kw_low in skill_lower or skill_lower in kw_low:
                matched.add(original)
                distribution["skills"].append(original)

    # Projects
    for proj in tailored_data.get("projects", []):
        proj_text = f"{proj.get('name', '')} {proj.get('description', '')}".lower()
        for kw_low, original in kw_lower.items():
            if kw_low in proj_text and original not in distribution["projects"]:
                matched.add(original)
                distribution["projects"].append(original)

    # Deduplicate distributions
    for key in distribution:
        distribution[key] = list(dict.fromkeys(distribution[key]))

    missing = [k for k in jd_keywords if k not in matched]
    coverage_pct = round(len(matched) / len(jd_keywords) * 100, 1) if jd_keywords else 0.0

    log.info("Keyword coverage: %d/%d (%.1f%%)", len(matched), len(jd_keywords), coverage_pct)
    return {
        "matched": sorted(matched, key=lambda x: jd_keywords.index(x) if x in jd_keywords else 999),
        "missing": sorted(missing, key=lambda x: jd_keywords.index(x) if x in jd_keywords else 999),
        "coverage_pct": coverage_pct,
        "distribution": distribution,
    }
