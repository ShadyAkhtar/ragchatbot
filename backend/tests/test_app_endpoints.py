"""
API endpoint tests for /api/courses, /api/new-chat, and the static-file root
("/"), against the real FastAPI app object (see conftest.py's module
docstring for how static file mounting is made to resolve correctly in the
test environment). `rag_system` methods are replaced per-test so no real
vector store search or LLM call ever runs.
"""
import app as app_module


class TestCoursesEndpointSuccess:
    def test_courses_endpoint_returns_200_with_expected_shape(self, client, mock_rag_analytics):
        mock_rag_analytics.return_value = {
            "total_courses": 2,
            "course_titles": ["Course A", "Course B"],
        }

        response = client.get("/api/courses")

        assert response.status_code == 200
        assert response.json() == {
            "total_courses": 2,
            "course_titles": ["Course A", "Course B"],
        }

    def test_courses_endpoint_reflects_zero_courses(self, client, mock_rag_analytics):
        mock_rag_analytics.return_value = {"total_courses": 0, "course_titles": []}

        response = client.get("/api/courses")

        assert response.status_code == 200
        assert response.json() == {"total_courses": 0, "course_titles": []}


class TestCoursesEndpointErrorHandling:
    def test_courses_endpoint_exception_returns_500_with_real_detail_message(self, client, mock_rag_analytics):
        mock_rag_analytics.side_effect = RuntimeError("ChromaDB unavailable")

        response = client.get("/api/courses")

        assert response.status_code == 500
        assert response.json()["detail"] == "ChromaDB unavailable"


class TestNewChatEndpoint:
    def test_new_chat_with_session_id_deletes_session_and_returns_success(self, client, mock_session_delete):
        response = client.post("/api/new-chat", json={"session_id": "session_1"})

        assert response.status_code == 200
        assert response.json() == {"success": True}
        mock_session_delete.assert_called_once_with("session_1")

    def test_new_chat_without_session_id_does_not_touch_session_manager(self, client, mock_session_delete):
        response = client.post("/api/new-chat", json={})

        assert response.status_code == 200
        assert response.json() == {"success": True}
        mock_session_delete.assert_not_called()

    def test_new_chat_exception_returns_500_with_real_detail_message(self, client, mock_session_delete):
        mock_session_delete.side_effect = RuntimeError("session store unavailable")

        response = client.post("/api/new-chat", json={"session_id": "session_1"})

        assert response.status_code == 500
        assert response.json()["detail"] == "session store unavailable"


class TestStaticRootEndpoint:
    def test_root_serves_frontend_index_html(self, client):
        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_missing_static_asset_returns_404(self, client):
        response = client.get("/does-not-exist.js")

        assert response.status_code == 404
