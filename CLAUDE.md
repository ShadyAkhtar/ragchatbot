# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for all Python dependency and execution management — do not use `pip`/`python` directly.

```bash
uv sync                                              # install/sync dependencies
```

Claude can be served via **AWS Bedrock** (default) or a **direct Anthropic API key** — see "Pluggable LLM provider" below. Create a `.env` in the project root (not `backend/`) before running. For Bedrock (default):
```
AWS_REGION=us-east-1
```
AWS credentials come from the standard AWS credential chain (`~/.aws/credentials`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars, or an assumed role) — nothing Bedrock-specific goes in `.env`. The Bedrock account must have model access granted for `BEDROCK_MODEL` (default `us.anthropic.claude-sonnet-5`, a Bedrock inference-profile ID) and a valid payment method on file, or calls fail with `AccessDeniedException`. To use a direct Anthropic API key instead, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...` (see `.env.example` for both modes).

Run the server (must run with `backend/` as the working directory — paths like `../docs` and `./chroma_db` are relative to it):
```bash
./run.sh                                             # quick start
# or manually:
cd backend && uv run uvicorn app:app --reload --port 8000
```

- Web UI: `http://localhost:8000`
- Swagger API docs: `http://localhost:8000/docs`

There is no test suite, linter, or formatter configured in this repo (no `tests/`, no lint config in `pyproject.toml`). Don't invent commands for these.

## Architecture

Full-stack RAG chatbot that answers questions about course transcripts. FastAPI backend (serves both the JSON API and the static frontend), ChromaDB as the vector store, Claude (Anthropic) for generation, vanilla JS frontend with no build step.

### Agentic RAG via tool-calling, not a fixed pipeline

The core design decision: Claude decides whether to search at all. `AIGenerator.generate_response()` (`backend/ai_generator.py`) gives Claude the `search_course_content` tool on the first `messages.create()` call. Only if `response.stop_reason == "tool_use"` does `_handle_tool_execution()` run the search and make a **second** Claude call — and that second call is made with no `tools` param, so Claude physically cannot chain another search. This is what enforces "one search per query maximum," not just the system prompt wording.

Request flow: `frontend/script.js` → `POST /api/query` (`backend/app.py`) → `RAGSystem.query()` (`backend/rag_system.py`, the orchestrator) → `AIGenerator` → optionally `ToolManager` → `CourseSearchTool` (`backend/search_tools.py`) → `VectorStore.search()` (`backend/vector_store.py`) → back through the same chain. Sources used in a search are tracked on `CourseSearchTool.last_sources` and pulled/reset by `RAGSystem` after each query — this is a stateful side channel, not part of the tool's return value, so anything touching source attribution has to go through `ToolManager.get_last_sources()`/`reset_sources()`.

### Two ChromaDB collections, different purposes

`VectorStore` (`backend/vector_store.py`) maintains:
- `course_catalog` — one entry per course, keyed by course title as the document ID. Used only to fuzzy-resolve a `course_name` argument to an exact title via embedding similarity (`_resolve_course_name`), not for content search. Lesson metadata is stored JSON-serialized in `lessons_json` since Chroma metadata values can't be nested structures.
- `course_content` — one entry per chunk, metadata = `course_title`/`lesson_number`/`chunk_index`. This is what `search()` actually queries, after building a `where` filter from the resolved course title and/or lesson number.

Both collections share the same `SentenceTransformerEmbeddingFunction` (`all-MiniLM-L6-v2`), computed locally — no embedding API calls.

### Document ingestion is format-agnostic in name only

`DocumentProcessor.read_file()` opens every file as plain UTF-8 text regardless of extension. `RAGSystem.add_course_folder()` accepts `.pdf`/`.docx`/`.txt` by filename filter, but there is no PDF/DOCX parsing library anywhere in the codebase — only `.txt` is actually usable today. Adding real multi-format support means adding a parser per type before `read_file()`, not just relaxing the filter.

Every accepted file must follow a fixed transcript structure that `process_course_document()` (`backend/document_processor.py`) parses positionally:
```
Course Title: ...
Course Link: ...
Course Instructor: ...

Lesson 0: <title>
Lesson Link: ...
<lesson content>

Lesson 1: <title>
...
```
Chunking (`chunk_text`) splits on sentence boundaries into `CHUNK_SIZE`/`CHUNK_OVERLAP`-based windows (config in `backend/config.py`). The first chunk of each lesson (and, inconsistently, *every* chunk of the last lesson processed — see lines ~186 vs ~234) gets a `"Lesson N content: ..."` / `"Course X Lesson N content: ..."` prefix injected for retrieval context; be aware of this asymmetry if changing chunk formatting.

Ingestion on startup (`app.py`'s `startup` event, pointed at `../docs`) is dedup'd by course title but not incremental — new/changed files require a server restart, and there's no re-processing of a changed file with the same title.

### Session memory is in-process and ephemeral

`SessionManager` (`backend/session_manager.py`) keeps conversation history entirely in a dict in memory, capped at `MAX_HISTORY` exchanges (config, default 2). It is not persisted anywhere — restarting the server drops all sessions. History is formatted as plain `"Role: content"` lines and injected into Claude's system prompt as a text block, not passed as structured message history.

### Key config knobs (`backend/config.py`)

All tuning (chunk size/overlap, top-k results, history length, Chroma path, LLM provider settings) lives in one `Config` dataclass loaded from `.env` via `python-dotenv`.

### Pluggable LLM provider (`backend/llm_providers.py`)

`AIGenerator` doesn't construct an Anthropic client itself — it takes an `LLMProvider` (`build_client()` + `resolve_model()`) and is agnostic to which one it got. `create_provider(config)` picks `BedrockProvider` or `AnthropicAPIProvider` based on `config.LLM_PROVIDER` ("bedrock" | "anthropic"), each with its own model-id setting (`BEDROCK_MODEL` vs `ANTHROPIC_MODEL` — **these are different ID spaces and not interchangeable**: Bedrock wants an inference-profile ID like `us.anthropic.claude-sonnet-5`, the direct API wants a plain model name like `claude-sonnet-4-20250514`; picking the wrong format fails at request time, not at startup).

This works because `anthropic.Anthropic`, `anthropic.AnthropicBedrock`, and (if ever added) `anthropic.AnthropicVertex` all expose the identical `messages.create()` interface and response shape — so the adapter only needs to swap client construction, not response parsing. Adding Vertex AI support later is a ~15-line `LLMProvider` subclass + one `config.py` branch. Adding a genuinely different vendor (OpenAI, etc.) is **not** covered by this seam — the tool-calling loop in `AIGenerator._handle_tool_execution()` manipulates Anthropic's raw content-block format directly (`tool_use`/`tool_result` blocks, `stop_reason`), so a non-Anthropic vendor would need normalization there too, not just a new provider class.

`AIGenerator._extract_text()` scans `response.content` for the first `type == "text"` block rather than assuming `content[0]` — some models (e.g. Claude Sonnet 5) can prepend a `ThinkingBlock` for extended thinking, which has no `.text` attribute.
