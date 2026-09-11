# JobSphere — Active Job Pipeline Dashboard

Search, track, and manage job opportunities across multiple platforms — all from one dashboard.

## What is this?

JobSphere is a full-stack application that helps you:

- **Search jobs** using natural language ("React developer remote 4 years experience")
- **Browse results** from LinkedIn, Naukri, Indeed, and 50+ other sites via SearXNG
- **Save & filter** listings by source, job type, location, or keyword
- **Upload your resume** and get it parsed into structured data
- **Tailor resumes** to specific job descriptions and generate cover letters

## Quick Start

### One-command setup

If you have all the prerequisites installed, just run:

```bash
# Open Git Bash (Windows) or a terminal (Linux/macOS)
bash start.sh
```

This starts everything in order:
1. Docker services (SearXNG search engine, Camofox browser)
2. Ollama (local LLM)
3. MCP servers (search + browse)
4. Backend API (port 8000)
5. Frontend (port 5173)

Press **CTRL+C** to shut everything down cleanly.

### What you'll need

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | For the backend API |
| Node.js | 18+ | For the frontend |
| npm | — | Comes with Node.js |
| Docker | Latest | Runs SearXNG and Camofox |
| Ollama | Latest | Runs the local LLM |

### Starting services manually

If you prefer to start each piece yourself:

```bash
# 1. Start the backend
cd backend
python -m app.agents.nodes.job_mcp_server       # MCP Search (port 8001)
python -m app.agents.nodes.job_mcp_browse_server # MCP Browse (port 8002)
uvicorn app.main:app --reload                     # API (port 8000)

# 2. In another terminal, start the frontend
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173** in your browser.

## Project Structure

```
├── start.sh              # One-command launcher for everything
├── backend/              # FastAPI Python backend
│   ├── app/
│   │   ├── api/v1/       # REST endpoints (jobs, resumes)
│   │   ├── agents/       # AI agents for search + extraction
│   │   ├── core/         # Config, database, LLM provider
│   │   └── services/     # Resume parsing, tailoring, PDF generation
│   ├── migrations/       # MongoDB schema migrations
│   └── services/         # Docker Compose for SearXNG + Camofox
├── frontend/             # React + TypeScript + Vite
│   └── src/
│       ├── features/     # Dashboard, discovery, resumes, applications
│       ├── context/      # App-wide state management
│       └── services/     # API client
└── docs/                 # Architecture docs and specs
```

## Detailed Docs

- **Backend README** — full API reference, environment setup, migrations → [`backend/Readme.md`](backend/Readme.md)
- **Frontend README** — component architecture, tech stack → [`frontend/README.md`](frontend/README.md)
- **Architecture docs** — workflow diagrams and design specs → [`docs/`](docs/)
- **Startup script** — `bash start.sh` launches everything with one command

## Need help?

If something isn't working, check the logs:

```bash
cat logs/backend.log      # Backend errors
cat logs/frontend.log     # Frontend errors
cat logs/mcp-search.log   # MCP Search server
cat logs/mcp-browse.log   # MCP Browse server
```

Or refer to the detailed docs in [`docs/`](docs/) for architecture decisions and setup guides.
<!-- Test -->