"""
Tests for how RAGSystem.query() handles content-related questions end-to-end,
with the LLM boundary mocked but the real ToolManager/CourseSearchTool/
CourseOutlineTool wired to a mocked VectorStore.
"""
from unittest.mock import Mock

import pytest

from rag_system import RAGSystem


@pytest.fixture
def rag(monkeypatch, mock_vector_store, test_config):
    monkeypatch.setattr("rag_system.VectorStore", lambda *a, **kw: mock_vector_store)
    monkeypatch.setattr("rag_system.create_provider", lambda cfg: Mock())

    system = RAGSystem(test_config)
    system.ai_generator = Mock()
    return system


class TestQueryContentQuestions:
    def test_query_content_question_triggers_tool_and_returns_populated_sources(self, rag, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results

        def fake_generate_response(**kwargs):
            kwargs["tool_manager"].execute_tool("search_course_content", query="RAG basics")
            return "Here is the answer"

        rag.ai_generator.generate_response.side_effect = fake_generate_response

        answer, sources = rag.query("What is RAG?")

        assert answer == "Here is the answer"
        assert sources != []
        assert sources[0]["text"] == "Test Course: RAG Fundamentals - Lesson 1"

    def test_query_sources_reset_after_each_call_no_leakage_across_calls(self, rag, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results

        def searching_response(**kwargs):
            kwargs["tool_manager"].execute_tool("search_course_content", query="RAG basics")
            return "First answer"

        rag.ai_generator.generate_response.side_effect = searching_response
        rag.query("first question")

        rag.ai_generator.generate_response.side_effect = None
        rag.ai_generator.generate_response.return_value = "Second answer, no search"
        answer, sources = rag.query("second question")

        assert answer == "Second answer, no search"
        assert sources == []

    def test_query_general_knowledge_question_no_tool_call_returns_empty_sources(self, rag, mock_vector_store):
        rag.ai_generator.generate_response.return_value = "General knowledge answer"

        answer, sources = rag.query("What is 2+2?")

        assert answer == "General knowledge answer"
        assert sources == []
        mock_vector_store.search.assert_not_called()


class TestQuerySessionHandling:
    def test_query_with_session_id_fetches_history_and_passes_to_generator(self, rag):
        rag.ai_generator.generate_response.return_value = "an answer"
        session_id = rag.session_manager.create_session()
        rag.session_manager.add_exchange(session_id, "prior q", "prior a")

        rag.query("new q", session_id=session_id)

        history = rag.ai_generator.generate_response.call_args.kwargs["conversation_history"]
        assert history is not None
        assert "prior q" in history

    def test_query_with_session_id_calls_add_exchange_with_correct_args(self, rag):
        rag.ai_generator.generate_response.return_value = "the answer"
        session_id = rag.session_manager.create_session()

        rag.query("new q", session_id=session_id)

        updated_history = rag.session_manager.get_conversation_history(session_id)
        assert "new q" in updated_history
        assert "the answer" in updated_history

    def test_query_without_session_id_does_not_touch_session_manager(self, rag):
        rag.ai_generator.generate_response.return_value = "an answer"

        rag.query("q", session_id=None)

        assert rag.session_manager.sessions == {}


class TestQueryErrorPropagation:
    def test_query_propagates_exception_raised_by_ai_generator(self, rag):
        """
        RAGSystem.query() has no try/except of its own - an exception from
        ai_generator.generate_response (e.g. a Bedrock throttling error)
        propagates unchanged out to the caller, i.e. straight into app.py's
        blanket except-handler.
        """
        rag.ai_generator.generate_response.side_effect = RuntimeError("Bedrock throttling: ThrottlingException")

        with pytest.raises(RuntimeError, match="Bedrock throttling"):
            rag.query("content question")
