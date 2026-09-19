"""
Tests verifying AIGenerator correctly drives Claude's sequential tool-calling
protocol: up to 2 rounds of tool execution, each a separate API request, with
graceful handling when a tool call fails. All assertions are external/
black-box - only on `ai_generator.client.messages.create` call args/count,
`tool_manager.execute_tool` calls, and the returned string.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


class TestGenerateResponseToolWiring:
    def test_generate_response_includes_tools_and_tool_choice_when_tools_passed(
        self, ai_generator, make_response, make_text_block
    ):
        ai_generator.client.messages.create.return_value = make_response(
            stop_reason="end_turn", content=[make_text_block("Hi")]
        )

        ai_generator.generate_response(
            query="q", tools=[{"name": "x"}], tool_manager=None
        )

        kwargs = ai_generator.client.messages.create.call_args.kwargs
        assert kwargs["tools"] == [{"name": "x"}]
        assert kwargs["tool_choice"] == {"type": "auto"}

    def test_generate_response_omits_tools_key_when_tools_not_passed(
        self, ai_generator, make_response, make_text_block
    ):
        ai_generator.client.messages.create.return_value = make_response(
            stop_reason="end_turn", content=[make_text_block("Hi")]
        )

        ai_generator.generate_response(query="q")

        kwargs = ai_generator.client.messages.create.call_args.kwargs
        assert "tools" not in kwargs
        assert "tool_choice" not in kwargs

    def test_generate_response_returns_text_directly_when_stop_reason_not_tool_use(
        self, ai_generator, make_response, make_text_block
    ):
        ai_generator.client.messages.create.return_value = make_response(
            stop_reason="end_turn", content=[make_text_block("Hi")]
        )
        tool_manager = Mock()

        result = ai_generator.generate_response(query="q", tool_manager=tool_manager)

        assert result == "Hi"
        tool_manager.execute_tool.assert_not_called()
        assert ai_generator.client.messages.create.call_count == 1


class TestSingleRoundToolExecution:
    def test_generate_response_calls_execute_tool_with_exact_name_and_kwargs_on_tool_use(
        self, ai_generator, make_response, make_text_block, make_tool_use_block
    ):
        first_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_1",
                    name="search_course_content",
                    input={"query": "RAG", "course_name": "MCP"},
                )
            ],
        )
        second_response = make_response(
            stop_reason="end_turn", content=[make_text_block("Final answer")]
        )
        ai_generator.client.messages.create.side_effect = [
            first_response,
            second_response,
        ]

        tool_manager = Mock()
        tool_manager.execute_tool.return_value = "tool result text"

        result = ai_generator.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=tool_manager,
        )

        tool_manager.execute_tool.assert_called_once_with(
            "search_course_content", query="RAG", course_name="MCP"
        )
        assert result == "Final answer"
        assert ai_generator.client.messages.create.call_count == 2

    def test_generate_response_second_call_includes_tools_and_has_three_messages(
        self, ai_generator, make_response, make_text_block, make_tool_use_block
    ):
        """
        The second API call must still offer tools - this is what lets Claude
        chain a second tool call after seeing round 1's results, fixing the
        original "gets empty response" bug.
        """
        first_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_1", name="search_course_content", input={"query": "RAG"}
                )
            ],
        )
        second_response = make_response(
            stop_reason="end_turn", content=[make_text_block("Final answer")]
        )
        ai_generator.client.messages.create.side_effect = [
            first_response,
            second_response,
        ]

        tool_manager = Mock()
        tool_manager.execute_tool.return_value = "tool result text"

        ai_generator.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=tool_manager,
        )

        second_call_kwargs = ai_generator.client.messages.create.call_args_list[
            1
        ].kwargs
        assert second_call_kwargs["tools"] == [{"name": "search_course_content"}]
        assert second_call_kwargs["tool_choice"] == {"type": "auto"}
        messages = second_call_kwargs["messages"]
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2] == {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_1",
                    "content": "tool result text",
                }
            ],
        }

    def test_generate_response_multiple_tool_use_blocks_each_executed_and_each_produce_a_tool_result(
        self, ai_generator, make_response, make_text_block, make_tool_use_block
    ):
        first_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_1", name="search_course_content", input={"query": "RAG"}
                ),
                make_tool_use_block(
                    id="tu_2", name="get_course_outline", input={"course_name": "MCP"}
                ),
            ],
        )
        second_response = make_response(
            stop_reason="end_turn", content=[make_text_block("Final answer")]
        )
        ai_generator.client.messages.create.side_effect = [
            first_response,
            second_response,
        ]

        tool_manager = Mock()
        tool_manager.execute_tool.side_effect = ["result A", "result B"]

        ai_generator.generate_response(query="q", tools=[{}], tool_manager=tool_manager)

        assert tool_manager.execute_tool.call_count == 2
        second_call_kwargs = ai_generator.client.messages.create.call_args_list[
            1
        ].kwargs
        tool_results = second_call_kwargs["messages"][2]["content"]
        assert tool_results == [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "result A"},
            {"type": "tool_result", "tool_use_id": "tu_2", "content": "result B"},
        ]


class TestTwoRoundToolExecution:
    def test_generate_response_two_rounds_executes_both_tools_and_returns_final_text(
        self, ai_generator, make_response, make_text_block, make_tool_use_block
    ):
        first_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_1", name="get_course_outline", input={"course_name": "X"}
                )
            ],
        )
        second_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_2",
                    name="search_course_content",
                    input={"query": "lesson 4 topic"},
                )
            ],
        )
        third_response = make_response(
            stop_reason="end_turn", content=[make_text_block("Complete answer")]
        )
        ai_generator.client.messages.create.side_effect = [
            first_response,
            second_response,
            third_response,
        ]

        tool_manager = Mock()
        tool_manager.execute_tool.side_effect = ["outline result", "search result"]

        result = ai_generator.generate_response(
            query="q", tools=[{}], tool_manager=tool_manager
        )

        assert tool_manager.execute_tool.call_count == 2
        tool_manager.execute_tool.assert_any_call("get_course_outline", course_name="X")
        tool_manager.execute_tool.assert_any_call(
            "search_course_content", query="lesson 4 topic"
        )
        assert result == "Complete answer"
        assert ai_generator.client.messages.create.call_count == 3

    def test_third_call_omits_tools_after_two_tool_rounds(
        self, ai_generator, make_response, make_text_block, make_tool_use_block
    ):
        first_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_1", name="get_course_outline", input={"course_name": "X"}
                )
            ],
        )
        second_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_2", name="search_course_content", input={"query": "q"}
                )
            ],
        )
        third_response = make_response(
            stop_reason="end_turn", content=[make_text_block("Complete answer")]
        )
        ai_generator.client.messages.create.side_effect = [
            first_response,
            second_response,
            third_response,
        ]

        tool_manager = Mock()
        tool_manager.execute_tool.side_effect = ["outline result", "search result"]

        ai_generator.generate_response(query="q", tools=[{}], tool_manager=tool_manager)

        call_args_list = ai_generator.client.messages.create.call_args_list
        assert "tools" in call_args_list[0].kwargs
        assert "tools" in call_args_list[1].kwargs
        assert "tools" not in call_args_list[2].kwargs
        assert "tool_choice" not in call_args_list[2].kwargs

    def test_generate_response_stops_after_two_rounds_even_if_second_round_is_again_tool_use(
        self, ai_generator, make_response, make_text_block, make_tool_use_block
    ):
        """
        If Claude asks for a third tool call, it must not be executed - the
        third API call is forced without tools, guaranteeing a non-empty
        final answer instead of the original "gets empty response" bug.
        """
        first_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_1", name="search_course_content", input={"query": "a"}
                )
            ],
        )
        second_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_2", name="search_course_content", input={"query": "b"}
                )
            ],
        )
        forced_final_response = make_response(
            stop_reason="end_turn", content=[make_text_block("Best-effort answer")]
        )
        ai_generator.client.messages.create.side_effect = [
            first_response,
            second_response,
            forced_final_response,
        ]

        tool_manager = Mock()
        tool_manager.execute_tool.side_effect = ["result A", "result B"]

        result = ai_generator.generate_response(
            query="q", tools=[{}], tool_manager=tool_manager
        )

        assert tool_manager.execute_tool.call_count == 2
        assert ai_generator.client.messages.create.call_count == 3
        assert result == "Best-effort answer"
        assert result


class TestGracefulToolErrorHandling:
    def test_tool_error_in_round_one_stops_further_rounds_and_returns_claude_composed_text(
        self, ai_generator, make_response, make_text_block, make_tool_use_block
    ):
        """
        A failing tool call must not raise - it's fed back to Claude as an
        error tool_result, and one more API call (without tools) lets Claude
        compose a graceful final answer.
        """
        first_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_1", name="search_course_content", input={"query": "q"}
                )
            ],
        )
        final_response = make_response(
            stop_reason="end_turn",
            content=[make_text_block("I couldn't find that, but here's what I know.")],
        )
        ai_generator.client.messages.create.side_effect = [
            first_response,
            final_response,
        ]

        tool_manager = Mock()
        tool_manager.execute_tool.side_effect = RuntimeError("ChromaDB connection lost")

        result = ai_generator.generate_response(
            query="q", tools=[{}], tool_manager=tool_manager
        )

        assert result == "I couldn't find that, but here's what I know."
        assert ai_generator.client.messages.create.call_count == 2
        second_call_kwargs = ai_generator.client.messages.create.call_args_list[
            1
        ].kwargs
        assert "tools" not in second_call_kwargs
        tool_result_message = second_call_kwargs["messages"][2]
        assert (
            "ChromaDB connection lost" in tool_result_message["content"][0]["content"]
        )

    def test_tool_error_in_round_two_still_returns_text_without_raising(
        self, ai_generator, make_response, make_text_block, make_tool_use_block
    ):
        first_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_1", name="get_course_outline", input={"course_name": "X"}
                )
            ],
        )
        second_response = make_response(
            stop_reason="tool_use",
            content=[
                make_tool_use_block(
                    id="tu_2", name="search_course_content", input={"query": "q"}
                )
            ],
        )
        final_response = make_response(
            stop_reason="end_turn", content=[make_text_block("Partial answer")]
        )
        ai_generator.client.messages.create.side_effect = [
            first_response,
            second_response,
            final_response,
        ]

        tool_manager = Mock()
        tool_manager.execute_tool.side_effect = [
            "outline result",
            RuntimeError("search backend down"),
        ]

        result = ai_generator.generate_response(
            query="q", tools=[{}], tool_manager=tool_manager
        )

        assert tool_manager.execute_tool.call_count == 2
        assert ai_generator.client.messages.create.call_count == 3
        assert result == "Partial answer"
        third_call_kwargs = ai_generator.client.messages.create.call_args_list[2].kwargs
        assert "tools" not in third_call_kwargs


class TestExtractText:
    def test_extract_text_skips_leading_non_text_block(
        self, ai_generator, make_response, make_text_block
    ):
        thinking_block = SimpleNamespace(type="thinking", text="internal reasoning")
        ai_generator.client.messages.create.return_value = make_response(
            stop_reason="end_turn",
            content=[thinking_block, make_text_block("the real answer")],
        )

        result = ai_generator.generate_response(query="q")

        assert result == "the real answer"
