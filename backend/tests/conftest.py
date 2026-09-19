"""
Shared fixtures for the backend test suite.

`backend/app.py` mounts static files with `StaticFiles(directory="../frontend")`,
which is resolved relative to the process's current working directory (not
`__file__`) at import time. We chdir to `backend/` here, before any test module
imports `app`, so that import succeeds regardless of where pytest is invoked from.

`pythonpath = ["backend"]` in pyproject.toml already puts `backend/` on
sys.path for imports like `from vector_store import VectorStore`; the
sys.path.insert below is redundant with that but keeps this file
self-sufficient if the suite is ever run without picking up the ini options.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from fastapi.testclient import TestClient

from models import Course, Lesson
from vector_store import VectorStore, SearchResults
from search_tools import CourseSearchTool, CourseOutlineTool, ToolManager
from llm_providers import LLMProvider
from ai_generator import AIGenerator
from config import Config
import app as app_module


# ---------------------------------------------------------------------------
# Domain model fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_lessons():
    return [
        Lesson(lesson_number=0, title="Introduction", lesson_link="https://example.com/l0"),
        Lesson(lesson_number=1, title="Getting Started", lesson_link="https://example.com/l1"),
        Lesson(lesson_number=2, title="Advanced Topics", lesson_link=None),
    ]


@pytest.fixture
def sample_course(sample_lessons):
    return Course(
        title="Test Course: RAG Fundamentals",
        course_link="https://example.com/course",
        instructor="Jane Doe",
        lessons=sample_lessons,
    )


@pytest.fixture
def sample_search_results():
    """Mixed lesson-level and course-level rows."""
    return SearchResults(
        documents=["Lesson 1 content about RAG basics.", "Course overview content."],
        metadata=[
            {"course_title": "Test Course: RAG Fundamentals", "lesson_number": 1},
            {"course_title": "Test Course: RAG Fundamentals", "lesson_number": None},
        ],
        distances=[0.1, 0.2],
    )


@pytest.fixture
def empty_search_results():
    return SearchResults(documents=[], metadata=[], distances=[])


@pytest.fixture
def error_search_results():
    return SearchResults.empty("No course found matching 'Nonexistent Course'")


# ---------------------------------------------------------------------------
# VectorStore / tool fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_vector_store():
    store = Mock(spec=VectorStore)
    store.get_course_link.return_value = "https://example.com/course"
    store.get_lesson_link.return_value = "https://example.com/l1"
    return store


@pytest.fixture
def search_tool(mock_vector_store):
    return CourseSearchTool(mock_vector_store)


@pytest.fixture
def outline_tool(mock_vector_store):
    return CourseOutlineTool(mock_vector_store)


@pytest.fixture
def tool_manager():
    return ToolManager()


@pytest.fixture
def populated_tool_manager(mock_vector_store):
    manager = ToolManager()
    manager.register_tool(CourseSearchTool(mock_vector_store))
    manager.register_tool(CourseOutlineTool(mock_vector_store))
    return manager


# ---------------------------------------------------------------------------
# Fake Anthropic SDK response fixtures
# ---------------------------------------------------------------------------
# Duck-typed SimpleNamespaces: AIGenerator only ever accesses .type/.text/
# .name/.input/.id on these objects, so real Pydantic SDK types add no
# behavioral fidelity here and would need every required field populated.

@pytest.fixture
def make_text_block():
    def _make(text):
        return SimpleNamespace(type="text", text=text)
    return _make


@pytest.fixture
def make_tool_use_block():
    def _make(id, name, input):
        return SimpleNamespace(type="tool_use", id=id, name=name, input=input)
    return _make


@pytest.fixture
def make_response():
    def _make(stop_reason, content):
        return SimpleNamespace(stop_reason=stop_reason, content=content)
    return _make


# ---------------------------------------------------------------------------
# AIGenerator fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_anthropic_client():
    client = Mock()
    client.messages = Mock()
    client.messages.create = Mock()
    return client


@pytest.fixture
def fake_llm_provider(mock_anthropic_client):
    provider = Mock(spec=LLMProvider)
    provider.build_client.return_value = mock_anthropic_client
    provider.resolve_model.return_value = "fake-model-id"
    return provider


@pytest.fixture
def ai_generator(fake_llm_provider):
    return AIGenerator(fake_llm_provider)


@pytest.fixture
def test_config():
    return Config()


# ---------------------------------------------------------------------------
# FastAPI app / endpoint fixtures
# ---------------------------------------------------------------------------
# These test against the real `app` object (see module docstring for why
# static file mounting resolves correctly here), with `rag_system` methods
# replaced per-test so no real vector store search or LLM call ever runs.

@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def mock_rag_query(monkeypatch):
    mock_query = Mock()
    monkeypatch.setattr(app_module.rag_system, "query", mock_query)
    monkeypatch.setattr(app_module.rag_system.session_manager, "create_session", Mock(return_value="session_1"))
    return mock_query


@pytest.fixture
def mock_rag_analytics(monkeypatch):
    mock_analytics = Mock()
    monkeypatch.setattr(app_module.rag_system, "get_course_analytics", mock_analytics)
    return mock_analytics


@pytest.fixture
def mock_session_delete(monkeypatch):
    mock_delete = Mock()
    monkeypatch.setattr(app_module.rag_system.session_manager, "delete_session", mock_delete)
    return mock_delete
