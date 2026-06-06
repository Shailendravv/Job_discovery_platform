Start MCP first
Run from Backend Directory
1. python -m app.agents.nodes.job_mcp_server

2. python -m app.agents.nodes.job_mcp_browse_server

Now run your main App
uvicorn app.main:app --reload