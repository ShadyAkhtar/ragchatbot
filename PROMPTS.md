# Session Prompt Log

A chronological record of the prompts given to Claude Code in this working session, and what was done in response.

---

### 1. "why the mcp for playwright failed?"
Diagnosed the Playwright MCP connection failure (`ENOENT: npx not found`). Root cause: Node.js/npm was not installed on the machine, so `npx` couldn't be resolved on `$PATH`.

### 2. "I have nvm"
Investigated the existing `nvm` install and found it had no Node version actually installed (`~/.nvm/versions/node` was empty).

### 3. "fix this using nvm"
Ran `nvm install --lts` to install Node v24.21.0. Updated the `playwright` MCP server entry in `~/.claude.json` to call the absolute path to nvm's `npx`, with `env.PATH` set to include nvm's `bin` directory (since `npx`'s `#!/usr/bin/env node` shebang needs `node` resolvable at runtime, and the running Claude Code process's own `$PATH` predates the Node install).

### 4. "Using the playwright MCP server visit 127.0.0.1:8000 and view the new chat button. I want that button to look the same as the other links below for Courses and Try Asking. Make sure this is left aligned and that the border is removed"
Discovered the local Chrome executable Playwright needed wasn't installed, installed a Playwright-managed Chromium, and pointed `--executable-path` at it in the MCP config. Verified in the browser that the `.new-chat-button` CSS (already present, uncommitted, in `frontend/style.css`) matched the sidebar header styling — left-aligned, no border — confirming the button already met the requirement.

### 5. "reload the server command and to stop"
Restarted the `uv run uvicorn` dev server (killed the existing process tree, relaunched via `run.sh`), verified it came back up cleanly, then stopped as instructed.

### 6. Add a course outline tool
> In `backend/search_tools.py`, add a second tool alongside the existing content-related tool. This new tool should handle course outline queries.
> - Input: Course title
> - Output: Course title, course link, and complete lesson list (lesson number + title per lesson)
> - Data source: Course metadata collection of the vector store
> - Update the system prompt in `backend/ai_generator` so outline queries return title, link, and lesson list
> - Register the new tool in the system

Implemented:
- `VectorStore.get_course_outline()` in `backend/vector_store.py` — resolves a course name and returns title, course link, and parsed lesson list from the `course_catalog` collection.
- `CourseOutlineTool` in `backend/search_tools.py`, exposed as the `get_course_outline` tool.
- Registered the new tool alongside `CourseSearchTool` in `backend/rag_system.py`.
- Updated `AIGenerator.SYSTEM_PROMPT` in `backend/ai_generator.py` to describe both tools and require outline answers to include course title, course link, and the full lesson list.
- Verified end-to-end via a live `/api/query` call against the running server.

### 7. "I dont want additional browser to get installed it ll just keep growing my disk space, better use my brave browser with playwright as brave browser is chromium based"
Repointed the Playwright MCP server's `--executable-path` at the user's installed Brave Browser instead of a Playwright-downloaded Chromium, then deleted the previously-downloaded Chromium/Chrome-headless-shell caches (~554MB freed). Playwright uses a separate automation profile directory, not the user's real Brave profile.

### 8. "please locate the "+ NEW CHAT" button using playwright"
Hit a stale browser-profile lock from an orphaned Chrome-for-Testing process left running after the cache cleanup; killed it, then used `browser_find` to locate the `+ New Chat` button (`#newChatButton`) in the page.

### 9. "commit and push it with all the prompts documenting in one md file"
Added this file, added `.playwright-mcp/` (browser automation scratch artifacts) to `.gitignore`, and committed/pushed all outstanding changes.
