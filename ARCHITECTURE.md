# Architecture Notes — Course Materials RAG System

## 1. Project Overview

A full-stack RAG (Retrieval-Augmented Generation) chatbot that answers questions about
course materials (educational transcripts), using ChromaDB for retrieval and Claude for
generation.

### Architecture

- **Backend**: FastAPI (Python 3.13, `uv`-managed) in `backend/app.py`, serving both the
  API and the static frontend.
- **Frontend**: Plain HTML/CSS/vanilla JS (no framework, no build step), in `frontend/`.
- **Vector DB**: ChromaDB (local, persistent at `./chroma_db`), two collections:
  - `course_catalog` — course metadata, used for fuzzy course-title matching.
  - `course_content` — chunked lesson text, used for semantic search.
- **Embeddings**: `sentence-transformers` `all-MiniLM-L6-v2`, computed locally (no
  external embedding API call).
- **LLM**: Anthropic Claude (`claude-sonnet-4-20250514`) via native tool-calling — Claude
  decides when to invoke a `search_course_content` tool rather than following a fixed
  retrieve-then-generate pipeline ("agentic RAG").
- **Session memory**: in-memory only, last 2 exchanges per session (lost on restart).

### Directory structure

```
/
├── README.md
├── pyproject.toml / uv.lock / .python-version
├── .env.example              # ANTHROPIC_API_KEY placeholder
├── run.sh                    # launches the server
├── main.py                   # unused stub — NOT the real entrypoint
├── backend/
│   ├── app.py                 # FastAPI app, routes, startup doc-loading, static mount
│   ├── config.py              # Config dataclass (model, chunk size, paths...), loads .env
│   ├── models.py               # Pydantic models: Course, Lesson, CourseChunk
│   ├── document_processor.py  # Parses raw course text files, chunking
│   ├── vector_store.py        # ChromaDB wrapper: collections, search, filtering
│   ├── ai_generator.py        # Anthropic API calls, system prompt, tool-use loop
│   ├── search_tools.py        # Tool abstraction, CourseSearchTool, ToolManager
│   ├── session_manager.py     # In-memory per-session conversation history
│   └── rag_system.py          # Orchestrator tying all components together
├── frontend/
│   ├── index.html             # Chat UI markup
│   ├── script.js              # fetch calls to /api/query and /api/courses
│   └── style.css
└── docs/
    └── course1_script.txt … course4_script.txt   # Sample course transcripts (seed data)
```

### Tech stack

| Concern        | Choice |
|-----------------|--------|
| Web server/API  | `fastapi==0.116.1` + `uvicorn==0.35.0` |
| LLM client      | `anthropic==0.58.2` (`claude-sonnet-4-20250514`) |
| Vector DB       | `chromadb==1.0.15` (persistent, local, path `./chroma_db`) |
| Embeddings      | `sentence-transformers==5.0.0` (`all-MiniLM-L6-v2`) |
| Frontend        | vanilla HTML/CSS/JS + `marked.js` (CDN) for markdown rendering |

### Running / developing

```bash
uv sync                     # install deps
# create .env with ANTHROPIC_API_KEY=...
./run.sh                    # or: cd backend && uv run uvicorn app:app --reload --port 8000
```

- Web UI: `http://localhost:8000`
- Swagger API docs: `http://localhost:8000/docs`

### Configuration (`backend/config.py`)

| Setting | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | from `.env` | only required env var |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | hardcoded, not env-driven |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | |
| `CHUNK_SIZE` | 800 (chars) | |
| `CHUNK_OVERLAP` | 100 (chars) | |
| `MAX_RESULTS` | 5 | top-k retrieval |
| `MAX_HISTORY` | 2 | conversation turns remembered per session |
| `CHROMA_PATH` | `./chroma_db` | relative to `backend/` (server cwd) |

Other notes:
- CORS and `TrustedHost` middleware are wide open (`allow_origins=["*"]`,
  `allowed_hosts=["*"]`) — fine for local dev, would need tightening for production.
- No authentication on any endpoint.
- Startup document ingestion is idempotent (skips courses already present by title) but
  not incremental/watching — new files require a server restart to be picked up.

---

## 2. Document Ingestion & Processing

All documents are processed **identically regardless of file type** — there is no
format-specific parsing.

### File discovery

`RAGSystem.add_course_folder` (`rag_system.py:79-81`) scans a directory (`../docs` on
startup) and accepts files ending in `.pdf`, `.docx`, or `.txt`.

### Reading

`DocumentProcessor.read_file` (`document_processor.py:13-21`) opens **every** accepted
file as plain UTF-8 text (falling back to `errors='ignore'` on decode failure).

> **Gap**: there is no PDF or DOCX parser anywhere in the codebase (no `PyPDF2`,
> `pdfplumber`, `python-docx`, etc.). The `.pdf`/`.docx` extensions are accepted by the
> folder scan in name only — if such a file were dropped into `docs/`, it would be read
> as raw bytes decoded as text, producing garbled/unusable content. Currently latent
> since only `.txt` files exist in `docs/`.

### Parsing (`DocumentProcessor.process_course_document`, lines 97–259)

Every file must follow a fixed transcript format:

1. Line 1: `Course Title: ...`
2. Line 2: `Course Link: ...`
3. Line 3: `Course Instructor: ...`
4. Remaining lines: `Lesson N: <title>` markers (optionally followed by
   `Lesson Link: ...`), each starting a new lesson's content block.

If line 1 doesn't match `Course Title:`, the processor falls back to using the raw line
as the title — malformed files degrade gracefully rather than erroring.

### Chunking (`DocumentProcessor.chunk_text`, lines 25–91)

- Sentence-boundary splitting via regex (handles common abbreviations).
- Packs sentences into chunks up to `CHUNK_SIZE` (800 chars) with `CHUNK_OVERLAP`
  (100 chars) of trailing-sentence overlap between consecutive chunks.
- The first chunk of each lesson is prefixed with `"Lesson N content: ..."` to preserve
  retrieval context.
- The **last** lesson processed in a file additionally gets every chunk prefixed with
  `"Course <title> Lesson N content: ..."` (line 234) — this differs from the
  first-chunk-only prefixing used for other lessons (line 186), which looks like an
  inconsistency rather than an intentional design choice.
- **Fallback**: if no `Lesson N:` markers are found at all, the entire remaining content
  is chunked as one undifferentiated document (lines 246–257).

### Storage (`VectorStore`, ChromaDB)

Two collections, both embedded with the same `SentenceTransformerEmbeddingFunction`
(`all-MiniLM-L6-v2`):

- **`course_catalog`** — one doc per course (title as ID); metadata includes instructor,
  course link, and a JSON-serialized lessons list. Used purely for fuzzy course-name
  resolution via embedding similarity.
- **`course_content`** — one doc per chunk; metadata = `course_title` / `lesson_number` /
  `chunk_index`. Used for actual semantic content search.

### Deduplication

`add_course_folder` fetches existing course titles from the vector store first and skips
re-processing/re-adding any course whose title already exists.

---

## 3. Query Handling — Frontend to Backend Trace

### 1. Frontend — user sends a message
`frontend/script.js:45-96` (`sendMessage`)
- Reads and clears `chatInput`, disables input, renders the user's message + a loading
  bubble.
- `POST /api/query` with JSON body `{ query, session_id: currentSessionId }`
  (`session_id` is `null` on the first message).

### 2. FastAPI endpoint
`backend/app.py:56-74` (`query_documents`)
- Parses body into `QueryRequest`.
- If `session_id` is missing, creates one via
  `rag_system.session_manager.create_session()`.
- Calls `rag_system.query(request.query, session_id)`.

### 3. RAGSystem orchestration
`backend/rag_system.py:102-140` (`query`)
- Wraps the raw query: `f"Answer this question about course materials: {query}"`.
- Pulls prior conversation history for the session (last 2 exchanges).
- Calls `ai_generator.generate_response(query=prompt, conversation_history=history,
  tools=tool_manager.get_tool_definitions(), tool_manager=tool_manager)`.

### 4. First Claude call
`backend/ai_generator.py:43-87` (`generate_response`)
- Builds `system` = static `SYSTEM_PROMPT` + injected conversation history.
- Calls `client.messages.create(...)` with the `search_course_content` tool available,
  `tool_choice: auto`, `temperature=0`, `max_tokens=800`.
- Claude decides: answer directly from general knowledge, **or** emit a `tool_use` block
  requesting `search_course_content(query, course_name?, lesson_number?)`.

### 5. Tool execution (only if Claude requested it)
`ai_generator.py:89-135` (`_handle_tool_execution`)
- For each `tool_use` block, calls
  `tool_manager.execute_tool("search_course_content", **input)` →
  `CourseSearchTool.execute()` (`search_tools.py:52-114`).
- `VectorStore.search()` resolves a fuzzy `course_name` against the `course_catalog`
  collection, builds a metadata `where` filter (course/lesson), then queries
  `course_content` for the top 5 chunks by embedding similarity.
- Results are formatted as `[Course - Lesson N]\n<chunk text>` blocks and returned as the
  tool result; sources (`"Course - Lesson N"` strings) are stashed on
  `CourseSearchTool.last_sources`.
- The tool result is appended as a `user`-role `tool_result` message, and Claude is
  called **again**, this time without tools, to synthesize the final natural-language
  answer from the retrieved context.

> Note: this loop only ever makes **one** round of tool calls — the final call is made
> with no `tools` param, so Claude cannot search again after seeing results. This
> structurally enforces the system prompt's "one search per query maximum" rule rather
> than relying on the model to follow it.

### 6. Back in RAGSystem
`rag_system.py:129-140`
- Pulls sources via `tool_manager.get_last_sources()`, then resets them.
- Records the exchange in `SessionManager` for future turns.
- Returns `(answer, sources)`.

### 7. FastAPI response
`app.py:66-72`
- Wraps into `QueryResponse{answer, sources, session_id}` and returns JSON.

### 8. Frontend renders result
`script.js:76-85`
- Removes the loading bubble, sets `currentSessionId` if newly created.
- Renders `data.answer` through `marked.parse()` (markdown → HTML) and, if `sources` is
  non-empty, appends a collapsible "Sources" section listing them.

```
User types query
      │
      ▼
frontend/script.js: sendMessage()
      │  POST /api/query {query, session_id}
      ▼
backend/app.py: query_documents()
      │  creates session if needed
      ▼
backend/rag_system.py: RAGSystem.query()
      │  wraps prompt + fetches history
      ▼
backend/ai_generator.py: generate_response()
      │  Claude call #1 (tools available)
      ▼
   tool_use? ──No──► return answer directly
      │Yes
      ▼
backend/ai_generator.py: _handle_tool_execution()
      │  → search_tools.py: CourseSearchTool.execute()
      │      → vector_store.py: VectorStore.search() (Chroma)
      │  Claude call #2 (no tools) → final answer
      ▼
rag_system.py: collect sources, update session history
      ▼
app.py: QueryResponse {answer, sources, session_id}
      ▼
frontend/script.js: render answer + sources
```
