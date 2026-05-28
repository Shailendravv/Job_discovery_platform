from app.agents.state import AgentState
from app.agents.tools.web_search import web_search


async def search_jobs_node(state: AgentState) -> AgentState:
    state["raw_jobs"] = web_search(
        state["query"],
        state.get("location"),
        num_results=10,
    )
    return state
