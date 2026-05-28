from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes.search_jobs import search_jobs_node
from app.agents.nodes.extract_skills import extract_skills_node

def build_job_search_graph():
    graph = StateGraph(AgentState)
    graph.add_node("search_jobs", search_jobs_node)
    graph.add_node("extract_skills", extract_skills_node)
    graph.set_entry_point("search_jobs")
    graph.add_edge("search_jobs", "extract_skills")
    graph.add_edge("extract_skills", END)
    return graph.compile()

def build_resume_tailor_graph():
    from app.agents.nodes.tailor_resume import tailor_resume_node
    graph = StateGraph(AgentState)
    graph.add_node("tailor_resume", tailor_resume_node)
    graph.set_entry_point("tailor_resume")
    graph.add_edge("tailor_resume", END)
    return graph.compile()

job_search_graph = build_job_search_graph()
resume_tailor_graph = build_resume_tailor_graph()
