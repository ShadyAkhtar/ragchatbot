"""
Tests against the real FastAPI app object, proving the backend preserves the
real error message in the 500 response's `detail` field - i.e. the "query
failed" bug the user sees is a frontend display issue (frontend/script.js
discards `detail`), not a backend information-loss issue.
"""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def mock_rag_query(monkeypatch):
    mock_query = Mock()
    monkeypatch.setattr(app_module.rag_system, "query", mock_query)
    monkeypatch.setattr(app_module.rag_system.session_manager, "create_session", Mock(return_value="session_1"))
    return mock_query


class TestQueryEndpointSuccess:
    def test_query_endpoint_success_returns_200_with_expected_shape(self, mock_rag_query):
        mock_rag_query.return_value = ("The answer", [{"text": "Course - Lesson 1", "link": "https://x"}])

        response = client.post("/api/query", json={"query": "what is RAG?"})

        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "The answer"
        assert body["sources"] == [{"text": "Course - Lesson 1", "link": "https://x"}]
        assert body["session_id"] == "session_1"

    def test_query_endpoint_source_dict_shape_matches_source_item_model(self, mock_rag_query):
        mock_rag_query.return_value = ("answer", [{"text": "Course - Lesson 1", "link": "https://x"}])

        response = client.post("/api/query", json={"query": "q"})

        assert set(response.json()["sources"][0].keys()) == {"text", "link"}

    def test_query_endpoint_reuses_provided_session_id(self, mock_rag_query):
        mock_rag_query.return_value = ("answer", [])

        client.post("/api/query", json={"query": "q", "session_id": "existing_session"})

        mock_rag_query.assert_called_once_with("q", "existing_session")
        app_module.rag_system.session_manager.create_session.assert_not_called()


class TestQueryEndpointErrorHandling:
    def test_query_endpoint_exception_returns_500_with_real_detail_message(self, mock_rag_query):
        """
        Proves the backend does NOT lose the real error - the error text the
        user sees as generic "Query failed" is a frontend-only display bug
        (frontend/script.js discards this `detail` field), not a backend one.
        """
        mock_rag_query.side_effect = RuntimeError("Bedrock throttling: ThrottlingException")

        response = client.post("/api/query", json={"query": "q"})

        assert response.status_code == 500
        assert response.json()["detail"] == "Bedrock throttling: ThrottlingException"
