"""
Tests for CourseSearchTool.execute(), CourseOutlineTool.execute(), and ToolManager.
"""
from vector_store import SearchResults


# ---------------------------------------------------------------------------
# CourseSearchTool.execute()
# ---------------------------------------------------------------------------

class TestCourseSearchToolExecute:
    def test_execute_with_results_formats_header_and_body(self, search_tool, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results

        result = search_tool.execute(query="what is RAG")

        assert "[Test Course: RAG Fundamentals - Lesson 1]" in result
        assert "Lesson 1 content about RAG basics." in result
        assert "[Test Course: RAG Fundamentals]" in result
        assert "Course overview content." in result

    def test_execute_populates_last_sources_with_correct_text_and_link(self, search_tool, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results

        search_tool.execute(query="what is RAG")

        assert search_tool.last_sources == [
            {"text": "Test Course: RAG Fundamentals - Lesson 1", "link": "https://example.com/l1"},
            {"text": "Test Course: RAG Fundamentals", "link": "https://example.com/course"},
        ]
        mock_vector_store.get_lesson_link.assert_called_once_with("Test Course: RAG Fundamentals", 1)
        mock_vector_store.get_course_link.assert_called_once_with("Test Course: RAG Fundamentals")

    def test_execute_lesson_link_falls_back_to_course_link_when_lesson_link_is_none(self, search_tool, mock_vector_store, sample_search_results):
        mock_vector_store.get_lesson_link.return_value = None
        mock_vector_store.get_course_link.return_value = "https://example.com/course"
        mock_vector_store.search.return_value = sample_search_results

        search_tool.execute(query="what is RAG")

        assert search_tool.last_sources[0]["link"] == "https://example.com/course"

    def test_execute_passes_course_name_filter_through_to_search(self, search_tool, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results

        search_tool.execute(query="q", course_name="MCP")

        mock_vector_store.search.assert_called_once_with(query="q", course_name="MCP", lesson_number=None)

    def test_execute_passes_lesson_number_filter_through_to_search(self, search_tool, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results

        search_tool.execute(query="q", lesson_number=2)

        mock_vector_store.search.assert_called_once_with(query="q", course_name=None, lesson_number=2)

    def test_execute_passes_both_filters_through_to_search(self, search_tool, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results

        search_tool.execute(query="q", course_name="MCP", lesson_number=2)

        mock_vector_store.search.assert_called_once_with(query="q", course_name="MCP", lesson_number=2)

    def test_execute_empty_results_no_filters_message(self, search_tool, mock_vector_store, empty_search_results):
        mock_vector_store.search.return_value = empty_search_results

        result = search_tool.execute(query="q")

        assert result == "No relevant content found."

    def test_execute_empty_results_with_course_name_message(self, search_tool, mock_vector_store, empty_search_results):
        mock_vector_store.search.return_value = empty_search_results

        result = search_tool.execute(query="q", course_name="MCP")

        assert result == "No relevant content found in course 'MCP'."

    def test_execute_empty_results_with_lesson_number_message(self, search_tool, mock_vector_store, empty_search_results):
        mock_vector_store.search.return_value = empty_search_results

        result = search_tool.execute(query="q", lesson_number=3)

        assert result == "No relevant content found in lesson 3."

    def test_execute_empty_results_with_both_filters_message(self, search_tool, mock_vector_store, empty_search_results):
        mock_vector_store.search.return_value = empty_search_results

        result = search_tool.execute(query="q", course_name="MCP", lesson_number=3)

        assert result == "No relevant content found in course 'MCP' in lesson 3."

    def test_execute_empty_results_lesson_zero_included_in_message(self, search_tool, mock_vector_store, empty_search_results):
        """
        Regression test for the lesson-0 falsy-check bug in search_tools.py.
        Lesson 0 is a real, valid lesson number (every course has a "Lesson 0:
        Introduction"), but `if lesson_number:` treats 0 as falsy and silently
        drops it from the message. Expected to FAIL until search_tools.py is
        fixed to use `if lesson_number is not None:`.
        """
        mock_vector_store.search.return_value = empty_search_results

        result = search_tool.execute(query="q", lesson_number=0)

        assert result == "No relevant content found in lesson 0."

    def test_execute_returns_error_string_when_search_has_error(self, search_tool, mock_vector_store, error_search_results):
        mock_vector_store.search.return_value = error_search_results

        result = search_tool.execute(query="q", course_name="Nonexistent Course")

        assert result == "No course found matching 'Nonexistent Course'"
        assert search_tool.last_sources == []

    def test_last_sources_overwritten_not_accumulated_across_calls(self, search_tool, mock_vector_store, sample_search_results):
        single_result = SearchResults(
            documents=["Solo chunk."],
            metadata=[{"course_title": "Other Course", "lesson_number": 1}],
            distances=[0.1],
        )

        mock_vector_store.search.return_value = sample_search_results
        search_tool.execute(query="first")
        assert len(search_tool.last_sources) == 2

        mock_vector_store.search.return_value = single_result
        search_tool.execute(query="second")
        assert len(search_tool.last_sources) == 1


# ---------------------------------------------------------------------------
# CourseOutlineTool.execute()
# ---------------------------------------------------------------------------

class TestCourseOutlineToolExecute:
    def test_execute_outline_found_formats_title_link_and_lessons(self, outline_tool, mock_vector_store):
        mock_vector_store.get_course_outline.return_value = {
            "title": "Test Course",
            "course_link": "https://x",
            "lessons": [
                {"lesson_number": 1, "lesson_title": "Intro", "lesson_link": "https://x/1"},
                {"lesson_number": 0, "lesson_title": "Welcome", "lesson_link": None},
            ],
        }

        result = outline_tool.execute(course_name="Test")

        assert "Course Title: Test Course" in result
        assert "Course Link: https://x" in result
        welcome_idx = result.index("0. Welcome")
        intro_idx = result.index("1. Intro")
        assert welcome_idx < intro_idx

    def test_execute_outline_not_found_returns_message(self, outline_tool, mock_vector_store):
        mock_vector_store.get_course_outline.return_value = None

        result = outline_tool.execute(course_name="Bogus")

        assert result == "No course found matching 'Bogus'"

    def test_execute_outline_missing_course_link_renders_na(self, outline_tool, mock_vector_store):
        mock_vector_store.get_course_outline.return_value = {
            "title": "Test Course",
            "course_link": None,
            "lessons": [],
        }

        result = outline_tool.execute(course_name="Test")

        assert "Course Link: N/A" in result

    def test_outline_tool_has_no_last_sources_attribute(self, outline_tool):
        assert not hasattr(outline_tool, "last_sources")


# ---------------------------------------------------------------------------
# ToolManager
# ---------------------------------------------------------------------------

class TestToolManager:
    def test_register_tool_adds_tool_by_name_from_definition(self, tool_manager, search_tool):
        tool_manager.register_tool(search_tool)

        assert tool_manager.tools["search_course_content"] is search_tool

    def test_get_tool_definitions_returns_list_of_both_registered_tool_schemas(self, populated_tool_manager):
        definitions = populated_tool_manager.get_tool_definitions()

        assert len(definitions) == 2
        names = {d["name"] for d in definitions}
        assert names == {"search_course_content", "get_course_outline"}
        for d in definitions:
            assert {"name", "description", "input_schema"} <= d.keys()

    def test_execute_tool_unknown_name_returns_error_string_not_raise(self, tool_manager):
        result = tool_manager.execute_tool("nonexistent_tool", query="x")

        assert result == "Tool 'nonexistent_tool' not found"

    def test_execute_tool_dispatches_kwargs_to_correct_tool(self, populated_tool_manager, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results

        populated_tool_manager.execute_tool("search_course_content", query="q", course_name="X")

        mock_vector_store.search.assert_called_once_with(query="q", course_name="X", lesson_number=None)

    def test_get_last_sources_returns_sources_from_search_tool_and_skips_outline_tool(self, populated_tool_manager, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results
        mock_vector_store.get_course_outline.return_value = {"title": "T", "course_link": None, "lessons": []}

        populated_tool_manager.execute_tool("search_course_content", query="q")
        populated_tool_manager.execute_tool("get_course_outline", course_name="T")

        sources = populated_tool_manager.get_last_sources()
        assert sources != []

    def test_get_last_sources_returns_empty_list_when_no_tool_has_sources(self, populated_tool_manager):
        assert populated_tool_manager.get_last_sources() == []

    def test_reset_sources_clears_search_tool_last_sources_but_ignores_outline_tool(self, populated_tool_manager, mock_vector_store, sample_search_results):
        mock_vector_store.search.return_value = sample_search_results
        populated_tool_manager.execute_tool("search_course_content", query="q")

        populated_tool_manager.tools["search_course_content"].last_sources
        populated_tool_manager.reset_sources()

        assert populated_tool_manager.tools["search_course_content"].last_sources == []
