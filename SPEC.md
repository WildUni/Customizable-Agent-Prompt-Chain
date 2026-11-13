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

Loads `backend/.env` with `python-dotenv` (if the file exists) and exposes module-level constants. Every constant can be overridden by an environment variable of the same name. Real environment variables take precedence over `.env`.

| Constant          | Default              | Where it's set | Purpose |
|-------------------|----------------------|----------------|---------|
| `LLM_MODEL`       | `"qwen3:8b"`         | `config.py` (not a secret) | Default model name |
| `USE_FAKE_LLM`    | `False`              | `config.py` (not a secret) | `"true"` (case-insensitive) swaps in the fake LLM |
| `OPENAI_BASE_URL` | `None` (OpenAI's default URL) | `.env` | Base URL of any OpenAI-compatible API (OpenAI, Ollama, …) |
| `OPENAI_API_KEY`  | `None`, **no default** | `.env` | API key. It's a secret, so it never has a default. Only needed for real LLM calls. |
| `DATABASE_URL`    | `"sqlite:///./app.db"` | `.env` | Database URL used by `db.py` |

`backend/.env.example` lists the `.env` keys. Because every value except the API key has a default, and the API key is only read on the first real LLM call (2.2), **the app imports and the test suite runs without a `.env` file**. That's how CI runs.

### 2.2 LLM client — `backend/llm.py`

**`LLMSettings`** (Pydantic model): per-call generation settings.

| Field         | Type          | Default             | Validation |
|---------------|---------------|---------------------|------------|
| `model`       | `str`         | `config.LLM_MODEL`  | Not checked against a model list, because any OpenAI-compatible server may be used |
| `temperature` | `float`       | `0.7`               | `0 ≤ temperature ≤ 2` |
| `max_tokens`  | `int \| None` | `None` (omitted from the request) | `> 0` when set |
| `system`      | `str \| None` | `None` (no system message) | — |

Unknown fields are rejected (`extra="forbid"`), so a typo like `temp` is an error instead of being silently dropped. Values are checked when settings are created, for example when a chain is saved, so an invalid value fails then rather than when the API is called.

**`get_client() -> OpenAI`**: creates the OpenAI client the first time it's called, then caches it in the module-level `client`.
- If `config.OPENAI_API_KEY` is unset, it raises `RuntimeError` with a message pointing to `.env.example` / `USE_FAKE_LLM`.
- The client is never created at import time, so importing `llm` (directly, or through `models`) never needs a key.

**`complete(prompt: str, settings: LLMSettings | None = None) -> str`**
- If `config.USE_FAKE_LLM` is true, it returns `fake_complete(prompt, settings)` and never calls the API or needs a key.
- Otherwise it sends one chat completion: an optional system message, then the prompt as a user message.
- `max_tokens` is sent only when it isn't `None`.
- It returns the first choice's content, or `""` if the content is `None`.

**`fake_complete(prompt, settings=None) -> str`**: returns
`"Fake response to prompt: {prompt}"`. It's deterministic, for tests and offline development.

Tests: `backend/tests/test_llm.py`. The OpenAI client is monkeypatched, and an autouse fixture forces `USE_FAKE_LLM=False` and clears the cached client, so a developer's `.env` can't change the results.

### 2.3 Database — `backend/db.py`

- `engine`: created from `config.DATABASE_URL`. `check_same_thread=False` is passed only for SQLite URLs, because other databases reject it.
- `init_db()`: imports the table models and runs `SQLModel.metadata.create_all(engine)`.
- `get_session()`: a FastAPI dependency that yields a `Session`.

### 2.4 HTTP API — `backend/main.py`

CORS allows `http://localhost:5173` (the Vite dev server).

| Method | Path      | Request              | Response |
|--------|-----------|----------------------|----------|
| GET    | `/`       | —                    | `{"message": "Hello World"}` |
| GET    | `/health` | —                    | `{"status": "ok"}` |

Tests: `backend/tests/test_main.py`.

### 2.5 Known issues

1. The `ollama` dependency is unused, because Ollama is reached through the OpenAI-compatible client.
2. `main.py` still defines `PromptIn`, which no endpoint uses now that `/run` is gone.

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

**Field validation conventions** (apply to every model in this section unless noted):

- **Unknown fields are rejected** (`extra="forbid"`) on `Position`, `Node`, `Edge`, `ChainGraph`, `ChainCreate`, and the nested `LLMSettings`. The frontend must convert its editor objects (which carry UI fields like `selected`, `measured`, `dragging`) into these shapes before sending them; raw editor objects are rejected.
- **Graph ids** (`Node.id`, `Edge.id`) must be non-empty and must not start or end with whitespace. They are *rejected*, not trimmed, so the id the client holds is always the id that's stored. Whitespace inside an id (`"node 1"`) is allowed.
- Every violation raises a Pydantic `ValidationError`.

### 4.2 `Position`

| Field | Type    | Default | Notes |
|-------|---------|---------|-------|
| `x`   | `float` | `0`     | Canvas coordinate; visual only. Must be finite (no `NaN` / `±inf`). |
| `y`   | `float` | `0`     | Canvas coordinate; visual only. Must be finite (no `NaN` / `±inf`). |

Coordinates must be finite because `NaN` and infinity are not valid JSON and would corrupt the stored `graph` column.

### 4.3 `Node`

| Field             | Type          | Default            | Notes |
|-------------------|---------------|--------------------|-------|
| `id`              | `str`         | required           | Unique within the chain. Graph-id rules (see 4.1). Client-generated (e.g. a UUID) so the editor can create nodes offline. |
| `type`            | `"prompt"`    | `"prompt"`         | Node kind. Will grow (`"input"`, `"output"`, `"condition"`, …). |
| `label`           | `str`         | `""`               | Display name |
| `prompt_template` | `str`         | `""`               | Prompt text. Placeholder syntax for upstream outputs is defined by the executor (planned), e.g. `{{input}}`. |
| `settings`        | `LLMSettings` | `LLMSettings()`    | Reuses `llm.LLMSettings`, including its validation (2.2) |
| `position`        | `Position`    | `Position()`       | Visual only; ignored by execution |

### 4.4 `Edge`

| Field       | Type          | Default  | Notes |
|-------------|---------------|----------|-------|
| `id`        | `str`         | required | Unique within the chain. Graph-id rules (see 4.1). |
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
| `name`       | `str`             | Required, max 200 chars (validated by `ChainCreate`; see 4.7) |
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

**`ChainCreate.name`**: leading and trailing whitespace is trimmed first; the result must then be 1–200 characters. `"  My chain  "` is stored as `"My chain"`, and `"   "` is rejected.

**Where validation happens:** SQLModel table models (`Chain`) do **not** validate on construction. All client input must pass through `ChainCreate` (and `ChainGraph`) before it reaches the table. `Chain.get_graph()` re-validates on read.

### 4.8 Deferred validation

These are intentionally not validated yet:

- `Node.prompt_template` placeholders, which will be checked once the executor defines the placeholder syntax.
- `Edge.condition` syntax, which will be checked once branching is implemented.
- Length limits on `label` / `prompt_template`, which will be handled by request-size limits at the API layer.
- `LLMSettings.model` against a list of known models, because OpenAI-compatible servers (e.g. Ollama) make any fixed list wrong.

---

## 5. Roadmap (planned)

- **T06+: Chain CRUD endpoints** (`POST/GET/PUT/DELETE /chains`) built on the schemas in 4.7.
- **Executor:** run a chain in `topological_order()`, render each prompt template with upstream outputs, evaluate edge conditions, and record a Run.
- **Frontend:** graph editor (e.g. React Flow) that loads and saves `ChainGraph`.
