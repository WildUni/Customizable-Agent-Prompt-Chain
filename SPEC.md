# Functional Specification — Customizable Agent Prompt Chain

An interface for building customizable prompt chains: a user wires prompt nodes
together into a directed graph, and the backend runs the graph against an LLM.
Branching and conditionals are first-class goals.

This document describes what exists today and the specs for work in progress.
Sections marked **(planned)** are not implemented yet.

---

## 1. Architecture

| Part     | Stack                                   | Location    |
|----------|-----------------------------------------|-------------|
| Backend  | Python ≥ 3.11, FastAPI, SQLModel, OpenAI SDK, managed with `uv` | `backend/`  |
| Frontend | React + TypeScript, Vite, Vitest        | `frontend/` |
| Database | SQLite (`backend/app.db`)               | —           |
| CI       | GitHub Actions: `uv run pytest` (backend), `npx vitest run` (frontend) on every push and PR | `.github/workflows/ci.yml` |

---

## 2. Backend — current state

### 2.1 Configuration — `backend/config.py`

Loads `.env` with `python-dotenv` and exposes module-level constants:

| Constant          | Env var           | Default | Purpose |
|-------------------|-------------------|---------|---------|
| `OPENAI_BASE_URL` | `OPENAI_BASE_URL` | `None`  | Base URL of any OpenAI-compatible API (OpenAI, Ollama, …) |
| `OPENAI_API_KEY`  | `OPENAI_API_KEY`  | `None`  | API key |
| `LLM_MODEL`       | `LLM_MODEL`       | `None`  | Default model name |
| `DATABASE_URL`    | `DATABASE_URL`    | `None`  | Database URL (not used yet; see 2.3) |
| `USE_FAKE_LLM`    | `USE_FAKE_LLM`    | `False` | `"true"` (case-insensitive) swaps in the fake LLM |

### 2.2 LLM client — `backend/llm.py`

**`LLMSettings`** (Pydantic model): per-call generation settings.

| Field         | Type          | Default             |
|---------------|---------------|---------------------|
| `model`       | `str`         | `config.LLM_MODEL`  |
| `temperature` | `float`       | `0.7`               |
| `max_tokens`  | `int \| None` | `None` (omitted from the request) |
| `system`      | `str \| None` | `None` (no system message) |

**`complete(prompt: str, settings: LLMSettings | None = None) -> str`**
- If `config.USE_FAKE_LLM` is true, it returns `fake_complete(prompt, settings)` and never calls the API.
- Otherwise it sends one chat completion: an optional system message, then the prompt as a user message.
- `max_tokens` is sent only when it isn't `None`.
- It returns the first choice's content, or `""` if the content is `None`.

**`fake_complete(prompt, settings=None) -> str`**: returns
`"Fake response to prompt: {prompt}"`. It's deterministic, for tests and offline development.

Tests: `backend/tests/test_llm.py` (the OpenAI client is monkeypatched).

### 2.3 Database — `backend/db.py`

- `engine`: SQLite engine at `sqlite:///./app.db`, created with `check_same_thread=False`.
- `init_db()`: imports the table models and runs `SQLModel.metadata.create_all(engine)`.
- `get_session()`: a FastAPI dependency that yields a `Session`.

### 2.4 HTTP API — `backend/main.py`

CORS allows `http://localhost:5173` (the Vite dev server).

| Method | Path      | Request              | Response |
|--------|-----------|----------------------|----------|
| GET    | `/`       | —                    | `{"message": "Hello World"}` |
| GET    | `/health` | —                    | `{"status": "ok"}` |
| POST   | `/run`    | `{"prompt": string}` | `{"output": string}` (see known issues) |

### 2.5 Known issues

1. `POST /run` calls `run_prompt`, which is never defined, so the endpoint raises `NameError`. It should call `llm.complete`.
2. `.env.example` uses `OPENAI_MODEL`, but `config.py` reads `LLM_MODEL`. It also doesn't list `OPENAI_BASE_URL` or `USE_FAKE_LLM`.
3. `db.py` hard-codes the database URL instead of reading `config.DATABASE_URL`.
4. `tests/test_main.py` is commented out.
5. The `ollama` dependency is unused, because Ollama is reached through the OpenAI-compatible client.

---

## 3. Frontend — current state

Vite + React template scaffold (`frontend/src/App.tsx`), with one smoke test (`App.test.tsx`) that checks `App` renders. There's no chain UI yet.

---

## 4. Data model — Chain, Node, Edge (T05)

### 4.1 Concept

A **Chain** is a **directed acyclic graph (DAG)**:

- **Nodes** are units of work (for now, one LLM prompt each).
- **Edges** are directed connections that carry a node's output to another node.
- A node can have **any number of incoming and outgoing edges**. Several incoming edges merge inputs. Several outgoing edges fan out, and with conditions they become branches.
- Nodes never reference each other. Connectivity lives **only in the edges**.
- The model is a pure *definition*. Run results (outputs, errors, timings) belong in a separate Run model (planned, out of scope for T05).

The shape (lists of `nodes` with `id` + `position`, and `edges` with `source` / `target`) matches what node-editor libraries such as React Flow use, so the frontend can load it directly.

Code: `backend/models.py`. Tests: `backend/tests/test_models.py`.

### 4.2 `Position`

| Field | Type    | Default | Notes |
|-------|---------|---------|-------|
| `x`   | `float` | `0`     | Canvas coordinate; visual only |
| `y`   | `float` | `0`     | Canvas coordinate; visual only |

### 4.3 `Node`

| Field             | Type          | Default            | Notes |
|-------------------|---------------|--------------------|-------|
| `id`              | `str`         | required           | Unique within the chain. Non-empty. Client-generated (e.g. a UUID) so the editor can create nodes offline. |
| `type`            | `"prompt"`    | `"prompt"`         | Node kind. Will grow (`"input"`, `"output"`, `"condition"`, …). |
| `label`           | `str`         | `""`               | Display name |
| `prompt_template` | `str`         | `""`               | Prompt text. Placeholder syntax for upstream outputs is defined by the executor (planned), e.g. `{{input}}`. |
| `settings`        | `LLMSettings` | `LLMSettings()`    | Reuses `llm.LLMSettings` |
| `position`        | `Position`    | `Position()`       | Visual only; ignored by execution |

### 4.4 `Edge`

| Field       | Type          | Default  | Notes |
|-------------|---------------|----------|-------|
| `id`        | `str`         | required | Unique within the chain. Non-empty. |
| `source`    | `str`         | required | `id` of the node the edge leaves |
| `target`    | `str`         | required | `id` of the node the edge enters |
| `condition` | `str \| None` | `None`   | `None` = always taken. Reserved for branching; the condition syntax will be defined with the executor. |
| `label`     | `str`         | `""`     | Display text on the edge |

### 4.5 `ChainGraph`

The validated `nodes` + `edges` pair.

| Field   | Type         | Default |
|---------|--------------|---------|
| `nodes` | `list[Node]` | `[]`    |
| `edges` | `list[Edge]` | `[]`    |

**Validation rules.** Breaking any rule raises a Pydantic `ValidationError` with a message that names the offending id.

1. Node ids are unique.
2. Edge ids are unique.
3. Every edge's `source` and `target` refer to an existing node.
4. No self-loops (`source == target`).
5. No duplicate connections: at most one edge per `(source, target)` pair.
6. No cycles: the graph must be acyclic.

An empty graph is valid. Disconnected nodes are valid (the editor needs them while building).

**Query methods**

| Method | Returns |
|--------|---------|
| `get_node(node_id)` | The `Node`, or raises `KeyError` |
| `outgoing(node_id)` | `list[Edge]` whose `source == node_id`, in edge-list order |
| `incoming(node_id)` | `list[Edge]` whose `target == node_id`, in edge-list order |
| `roots()` | `list[Node]` with no incoming edges (entry points), in node-list order |
| `leaves()` | `list[Node]` with no outgoing edges (final outputs), in node-list order |
| `topological_order()` | `list[str]` of node ids where every node comes after all its predecessors. Deterministic: ties are broken by node-list order. |

### 4.6 `Chain` (database table)

| Column       | Type              | Notes |
|--------------|-------------------|-------|
| `id`         | `int`             | Primary key, auto-increment |
| `name`       | `str`             | Required |
| `graph`      | JSON              | Serialized `ChainGraph` |
| `created_at` | `datetime` (UTC)  | Set on creation |
| `updated_at` | `datetime` (UTC)  | Set on creation and on every `set_graph` |

The whole graph is stored as **one JSON column**. The editor saves the whole graph at once, and nodes and edges aren't queried on their own, so separate tables would add joins without any benefit. If per-node queries are ever needed, nodes and edges can be split into tables.

**Methods**
- `get_graph() -> ChainGraph`: parses and validates the stored JSON.
- `set_graph(graph: ChainGraph)`: stores the graph and bumps `updated_at`.

### 4.7 API schemas

| Schema        | Fields |
|---------------|--------|
| `ChainCreate` | `name: str`, `graph: ChainGraph = ChainGraph()` |
| `ChainRead`   | `id`, `name`, `graph: ChainGraph`, `created_at`, `updated_at` |

---

## 5. Roadmap (planned)

- **T06+: Chain CRUD endpoints** (`POST/GET/PUT/DELETE /chains`) built on the schemas in 4.7.
- **Executor:** run a chain in `topological_order()`, render each prompt template with upstream outputs, evaluate edge conditions, and record a Run.
- **Frontend:** graph editor (e.g. React Flow) that loads and saves `ChainGraph`.
