# Job Search Backend

## Prerequisites

Make sure the following services are running before starting the backend.

### Docker Services
Start SearXNG (search engine) and Camofox (headless browser) via Docker:
```bash
cd services
docker-compose up -d
```

| Service  | URL                        |
|----------|----------------------------|
| SearXNG  | http://localhost:8888      |
| Camofox  | http://localhost:9500      |

### Ollama (LLM)
Ensure Ollama is running with the required model:
```bash
ollama run qwen2.5-coder:1.5b
```
Ollama listens on `http://localhost:11434` by default.

---

## Environment Setup

Copy `.env` and fill in your values:
```
MONGODB_URI=<your-mongodb-uri>
SEARXNG_URL=http://localhost:8888
CAMOFOX_URL=http://localhost:9500
Ollama=http://localhost:11434
SEARCH_MAX_RESULTS=10
BROWSE_TOP_N=15
SEARCH_SITES=naukri.com,linkedin.com/jobs,apna.co,indeed.com,instahyre.com,shine.com,foundit.in
SEARCH_FRESH=true
SEARCH_CAREERS=false
```

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## Starting the App

Run all commands from the **backend directory**.

### Start MCP first

1. `python -m app.agents.nodes.job_mcp_server`

2. `python -m app.agents.nodes.job_mcp_browse_server`

| MCP Server   | Port  | Purpose                        |
|--------------|-------|--------------------------------|
| job_mcp_server        | 8001  | Web search via SearXNG |
| job_mcp_browse_server | 8002  | Page extraction via Camofox |

### Now run your main App
```bash
uvicorn app.main:app --reload
```

API available at `http://localhost:8000`

---

## Project Structure

```
backend/
├── app/
│   ├── agents/
│   │   ├── nodes/
│   │   │   ├── job_mcp_server.py        # MCP search server (port 8001)
│   │   │   └── job_mcp_browse_server.py # MCP browse server (port 8002)
│   │   ├── mcp_client.py                # MCP HTTP client (StreamableHTTP)
│   │   ├── search_provider.py           # SearchProvider wrapping MCP client
│   │   └── job_workflow.py              # Main search + extract workflow
│   ├── api/v1/
│   │   ├── jobs.py                      # POST /api/v1/jobs/search
│   │   └── resumes.py
│   ├── core/
│   │   ├── config.py                    # Settings from .env
│   │   └── llm.py                       # LLM provider (Ollama / Groq / Gemini)
│   └── main.py
├── services/
│   └── docker-compose.yml               # SearXNG + Camofox
├── requirements.txt
└── .env
```
