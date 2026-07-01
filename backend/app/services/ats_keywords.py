"""
JD Keyword Extraction for ATS-Optimized Resume Tailoring.

Extracts 15-20 keywords from a job description, categorizes them
into technical/domain/soft_skills, and returns structured data.
"""

import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can",
    "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "also", "well", "new", "good", "great",
    "please", "able", "work", "team", "role", "position", "job", "candidate",
    "qualification", "responsibility", "requirement", "skill", "experience",
    "including", "preferred", "plus", "year", "years", "level",
})

_TERMS_TECH = frozenset({
    "react", "react.js", "next.js", "vue", "angular", "node", "node.js",
    "express", "fastapi", "django", "flask", "spring", "python", "java",
    "javascript", "typescript", "golang", "rust", "c++", "c#", "ruby",
    "php", "sql", "nosql", "mongodb", "postgresql", "mysql", "redis",
    "docker", "kubernetes", "aws", "gcp", "azure", "ci/cd", "jenkins",
    "git", "github", "gitlab", "linux", "api", "rest", "graphql",
    "html", "css", "tailwind", "bootstrap", "sass", "webpack", "vite",
    "pytorch", "tensorflow", "langchain", "llm", "rag", "openai",
    "machine learning", "deep learning", "nlp", "computer vision",
    "data science", "analytics", "tableau", "power bi", "etl",
    "agile", "scrum", "jira", "confluence", "figma", "photoshop",
    "terraform", "ansible", "prometheus", "grafana", "elasticsearch",
})

_TERMS_SOFT = frozenset({
    "leadership", "communication", "collaboration", "teamwork",
    "problem-solving", "analytical", "critical thinking", "mentoring",
    "stakeholder management", "cross-functional", "agile", "scrum",
    "project management", "time management", "adaptability",
    "conflict resolution", "negotiation", "presentation",
    "written communication", "verbal communication",
})


def extract_jd_keywords(
    job_title: str,
    job_description: str,
    job_skills: list[str],
    max_keywords: int = 20,
    min_keyword_length: int = 3,
) -> dict:
    """
    Extract 15-20 keywords from a job description, categorised.

    Priority order:
      1. Explicit job_skills (highest — from MongoDB job document)
      2. Job title noun phrases
      3. Description noun phrases (heuristic extraction)

    Returns dict with keys: all_keywords, technical, domain, soft_skills, required, preferred.
    """
    result: dict[str, list[str]] = {
        "all_keywords": [],
        "technical": [],
        "domain": [],
        "soft_skills": [],
        "required": [],
        "preferred": [],
    }
    seen: set[str] = set()

    # Priority 1: explicit job_skills
    for skill in job_skills:
        skill_stripped = skill.strip()
        skill_lower = skill_stripped.lower()
        if not skill_lower or skill_lower in seen or len(skill_stripped) < min_keyword_length:
            continue
        seen.add(skill_lower)
        if _is_technical(skill_stripped):
            result["technical"].append(skill_stripped)
            result["required"].append(skill_stripped)
        elif _is_soft_skill(skill_stripped):
            result["soft_skills"].append(skill_stripped)
            result["preferred"].append(skill_stripped)
        else:
            result["domain"].append(skill_stripped)
            result["required"].append(skill_stripped)

    # Priority 2: title noun phrases
    for kw in _extract_noun_phrases(job_title):
        kw_lower = kw.lower()
        if kw_lower not in seen and len(kw) >= min_keyword_length:
            seen.add(kw_lower)
            result["domain"].append(kw.strip())

    # Priority 3: description noun phrases
    for kw in _extract_noun_phrases(job_description):
        kw_lower = kw.lower()
        if kw_lower not in seen and len(kw) >= min_keyword_length and kw_lower not in _STOPWORDS:
            seen.add(kw_lower)
            if _is_technical(kw):
                result["technical"].append(kw.strip())
            elif _is_soft_skill(kw):
                result["soft_skills"].append(kw.strip())
            else:
                result["domain"].append(kw.strip())

    # Build flat list: technical + domain + soft_skills, capped
    result["all_keywords"] = (result["technical"] + result["domain"] + result["soft_skills"])[:max_keywords]

    log.info(
        "JD keywords extracted: %d total (%d technical, %d domain, %d soft_skills)",
        len(result["all_keywords"]),
        len(result["technical"]), len(result["domain"]), len(result["soft_skills"]),
    )
    return result


def _extract_noun_phrases(text: str) -> list[str]:
    """Extract likely keyword phrases using heuristics."""
    if not text:
        return []
    text = text.replace("/", " / ").replace(",", " , ")

    tokens = text.split()
    phrases: list[str] = []

    for token in tokens:
        clean = token.strip("()[]{}.:;!?\"'")
        if not clean or len(clean) < 3:
            continue
        if clean.isdigit() or clean.lower() in _STOPWORDS:
            continue
        if clean[0].isupper() or clean.isupper() or (clean.islower() and len(clean) > 3):
            phrases.append(clean)
        if "-" in clean or "_" in clean:
            for part in re.split(r"[-_]", clean):
                if len(part) >= 3 and part.lower() not in _STOPWORDS:
                    phrases.append(part)

    # 2-gram phrases
    for i in range(len(tokens) - 1):
        pair = f"{tokens[i]} {tokens[i+1]}"
        clean_pair = pair.strip("()[]{}.:;!?\"'")
        tokens_lower = [t.lower().strip("()[]{}.,:;!?\"'") for t in tokens[i:i+2]]
        if all(len(t) >= 3 and t not in _STOPWORDS for t in tokens_lower):
            if clean_pair not in phrases:
                phrases.append(clean_pair)

    seen: set[str] = set()
    deduped: list[str] = []
    for p in phrases:
        p_lower = p.lower()
        if p_lower not in seen:
            seen.add(p_lower)
            deduped.append(p)
    return deduped


def _is_technical(term: str) -> bool:
    return term.lower().strip() in _TERMS_TECH


def _is_soft_skill(term: str) -> bool:
    return term.lower().strip() in _TERMS_SOFT
