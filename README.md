# ai-agent

Internal AI agent backend for [Jnana Farms](https://app.jnanafarms.com) — a FastAPI service that fronts a
[LangGraph](https://github.com/langchain-ai/langgraph) tool-calling agent so the internal team can ask
questions and make entries against the farm's operational database (cultivation pipeline, inventory,
attendance, WhatsApp orders, etc.) in natural language.

## How it fits together

```
api/routes.py     FastAPI routes: chat (SSE streaming), open-chat (resume a session), transcribe (voice → text)
  └─ api/deps.py       JWT auth dependency, shared by all routes

app/main.py        App entrypoint: builds the Postgres-backed LangGraph checkpointer and mounts the router

graph/graph.py      The agent itself: model, system prompt, tool list, and the LangGraph state machine
  └─ helpers/query_checker.py   Guards db_query_tool — rejects unsafe/non-SELECT SQL before it runs
  └─ helpers/schema_context.py  Hand-maintained schema map, injected into both the agent and the query checker

db/models.py        SQLAlchemy models + Pydantic request/response schemas
db/engine.py         (stub) intended home for the sync/async engine + session setup

ingestion/ingestion.py   PDF → OCR (PaddleOCR) → chunk → embed pipeline for document retrieval
helpers/chunking.py       Chunking strategy for ingested documents
memory/                   Long-term memory cache/retrieval for the agent
```

### Request flow

1. A client calls `POST /api/chat/` with a JWT, a message, and a `session_id`.
2. `verify_jwt_token` (`api/deps.py`) validates the token and extracts `sub`/`session_id`, which become the
   LangGraph thread id (`{sub}:{session_id}`) — this is how conversation state is scoped per user/session.
3. The compiled graph (`app.state.graph`, built once at startup with an `AsyncPostgresSaver` checkpointer)
   streams the run via `astream_events`; model tokens and a final `done` event are pushed back over SSE.
4. The agent (`graph/graph.py`) can call tools mid-run: query the database, grep the codebase, search the
   web, save notes, or POST structured entries to the main Jnana Farms API.

### Tools available to the agent

| Tool | Purpose |
|---|---|
| `db_query_tool` | Runs a SQL query through `QueryCheck` first (LLM- or regex-based safety check), then executes it read-only against the app DB |
| `grep` | Regex search over local files |
| `add_entries` | POSTs a structured entry to `app.jnanafarms.com`'s enterprise API |
| `save` | Reserved for persisting agent notes |
| `search` | Reserved for web search |

### Query safety

`helpers/query_checker.py` sits in front of every SQL query the agent tries to run. It supports two modes:

- **`llm`** — sends the query + `SCHEMA_CONTEXT` to a model and asks for a true/false safety verdict
- **`manual`** — regex-rejects anything containing a non-`SELECT` statement (`DROP`, `DELETE`, `INSERT`, …)

`graph.py` currently instantiates it with `check_method="LLM"`.

## Setup

Requires Python >=3.14 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

### Environment variables

Copy the variables below into a `.env` file at the repo root (never commit this file):

| Variable | Used by | Purpose |
|---|---|---|
| `DB_URL` | `graph/graph.py` | Async SQLAlchemy connection string for the app database |
| `CHKPT_URL` | `app/main.py` | Postgres connection string for the LangGraph checkpointer pool |
| `OPENCODE_API_BASE`, `OPENCODE_API` | `query_checker.py`, `graph.py` | OpenAI-compatible endpoint/key used for the LLM query checker and the secondary chat model |
| `JWT_SECRET_KEY`, `JWT_ALGORITHM` | `api/deps.py` | Verifying inbound auth tokens |
| `FRONTEND_URL` | `app/main.py` | Allowed CORS origin |
| `ENTERPRISE_TOKEN` | `graph/graph.py` (`add_entries`) | Bearer token for `app.jnanafarms.com`'s API |
| `OPENAI_API_KEY` | `api/routes.py` (`/api/transcribe`) | Whisper transcription |

### Running

```bash
uv run uvicorn app.main:app --reload
```

## Roadmap

- Wire the document ingestion pipeline (`ingestion/ingestion.py`, `helpers/chunking.py`) into the graph to
  power retrieval-augmented search over uploaded documents.
- Implement the `save` and `search` tools.
- Consolidate database engine/session setup into `db/engine.py`.
- Build out `memory/` for longer-term agent memory across sessions.
