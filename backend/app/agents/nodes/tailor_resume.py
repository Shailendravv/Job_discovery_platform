from app.agents.state import AgentState

async def tailor_resume_node(state: AgentState) -> AgentState:
    # TODO: use LLM to tailor resume_text to the job description
    state["tailored_resume"] = state.get("resume_text", "")
    return state
