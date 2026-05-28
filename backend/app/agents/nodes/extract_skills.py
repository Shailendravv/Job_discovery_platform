from app.agents.state import AgentState
from app.agents.tools.skill_extraction import extract_skills_from_text


async def extract_skills_node(state: AgentState) -> AgentState:
    jobs_with_skills = []
    for job in state.get("raw_jobs", []):
        description = (
            job.get("description") or job.get("snippet") or job.get("content") or ""
        )
        job["skills"] = extract_skills_from_text(description)
        jobs_with_skills.append(job)

    state["jobs_with_skills"] = jobs_with_skills
    return state
