<<<<<<< HEAD
# ASTRA

**Personal AI Operating System**

ASTRA is a modular personal AI platform designed around voice-first interaction, persistent memory, and extensible tool usage. It is not a chatbot — it is an intelligent assistant architecture built to evolve.

---

## Architecture

```
Experience Layer      → Orb, Voice, Chat, Notch (future)
Application Layer     → Conversations, Projects, Tasks, Files
AI / Intelligence     → Orchestrator, Providers, Context, Verification
Memory / Knowledge    → Short-term, Long-term, Episodic, Semantic, RAG
Tool / Action         → Registry, Execution, Permissions
Infrastructure        → Database, Events, Logging, Security
```

See [docs/architecture/overview.md](docs/architecture/overview.md) for the full architecture document.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React, TypeScript, Vite |
| Backend | Python, FastAPI |
| Database | PostgreSQL (pgvector-ready) |
| AI Provider | Gemini (abstracted — provider-independent) |

---

## Project Structure

```
astra/
├── frontend/          React + TypeScript + Vite
├── backend/           Python + FastAPI
├── shared/            Shared contracts (future)
├── docs/              Architecture & decisions
├── scripts/           Development & deployment scripts
├── data/              Runtime data (gitignored)
└── tests/             Shared test fixtures
```

---

## Getting Started

### Prerequisites

- Node.js 20+
- Python 3.11+
- PostgreSQL 16+ (or Docker)

### Quick Start with Docker

```bash
# Copy environment config
cp .env.example .env
# Edit .env with your API keys and settings

# Start all services
docker-compose up --build
```

### Manual Development Setup

#### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

#### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
# → http://localhost:8000
# → http://localhost:8000/docs (API documentation)
```

#### Database

```bash
# Start PostgreSQL via Docker (if not running locally)
docker-compose up postgres -d

# Run migrations (when models exist)
cd backend
alembic upgrade head
```

---

## Development

### API Health Check

```bash
curl http://localhost:8000/api/health
```

### Architecture Decisions

Major technical decisions are recorded in [docs/architecture/decisions/](docs/architecture/decisions/).

Use [docs/architecture/decisions/template.md](docs/architecture/decisions/template.md) for new decisions.

---

## Current Phase

**Foundation** — Repository structure, configuration, and architectural boundaries are established. No AI functionality is implemented yet. The system starts, serves the frontend, and responds to health checks.

---

## License

[MIT](LICENSE)
=======
# Project_Astra
>>>>>>> 2d7ed071b16dc748c6afeb210490acdc913d6514
