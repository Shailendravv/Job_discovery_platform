from typing import List

SKILL_KEYWORDS = [
    "python",
    "sql",
    "excel",
    "javascript",
    "react",
    "node",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "machine learning",
    "data analysis",
    "data science",
    "project management",
    "communication",
    "teamwork",
    "leadership",
    "presentation",
    "sales",
    "marketing",
    "crm",
    "analytics",
    "design",
    "testing",
    "automation",
    "cloud",
    "devops",
    "security",
    "networks",
    "documentation",
]


def extract_skills_from_text(text: str) -> List[str]:
    """Extract common skill keywords from job text."""
    if not text:
        return []

    normalized = text.lower()
    found: list[str] = []
    for keyword in SKILL_KEYWORDS:
        if keyword in normalized and keyword not in found:
            found.append(keyword)
    return found
