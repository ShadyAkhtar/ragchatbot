from typing import List, Optional, Dict, Any
from llm_providers import LLMProvider

class AIGenerator:
    """Handles interactions with Anthropic's Claude API for generating responses"""
    
    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to two tools: a content search tool and a course outline tool.

Tool Usage:
- Use `search_course_content` for questions about specific course content or detailed educational materials
- Use `get_course_outline` for questions about a course's outline, structure, syllabus, or lesson list
- You may use tools across up to 2 sequential rounds per query. After seeing a tool's results, you may call one more tool if you need additional information to answer completely — for example, looking up a course's outline to find a lesson title, then searching for content on that title
- Answer as soon as you have enough information; do not use a second round just because one is available. Most questions are fully answerable after a single tool call
- Only use a second round when the first round's results are a prerequisite for forming the next tool call (e.g. you needed a title, number, or name that only the first tool call revealed), or when a question genuinely requires combining results from two different lookups (comparisons, multi-part questions, or information spanning different courses/lessons)
- After 2 rounds of tool use, you must answer using whatever information you have gathered — no further tool calls are available
- Synthesize tool results into accurate, fact-based responses
- If a tool yields no results or fails, state this clearly without offering alternatives

Outline Responses:
- When answering an outline-related query, always include the course title, the course link, and the full lesson list from the tool result
- For each lesson, include both its number and its title

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without using tools
- **Course-specific questions**: Use the appropriate tool(s) first, then answer
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, tool explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""

    # Maximum number of sequential tool-calling rounds per user query.
    MAX_TOOL_ROUNDS = 2

    def __init__(self, provider: LLMProvider):
        self.client = provider.build_client()
        self.model = provider.resolve_model()
        
        # Pre-build base API parameters
        # Note: `temperature` is deprecated/rejected for newer models (e.g. Claude Sonnet 5) - omit it.
        self.base_params = {
            "model": self.model,
            "max_tokens": 800
        }
    
    def generate_response(self, query: str,
                         conversation_history: Optional[str] = None,
                         tools: Optional[List] = None,
                         tool_manager=None) -> str:
        """
        Generate AI response with optional tool usage and conversation context.
        
        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use
            tool_manager: Manager to execute tools
            
        Returns:
            Generated response as string
        """
        
        # Build system content efficiently - avoid string ops when possible
        system_content = (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history 
            else self.SYSTEM_PROMPT
        )
        
        # Prepare API call parameters efficiently
        api_params = {
            **self.base_params,
            "messages": [{"role": "user", "content": query}],
            "system": system_content
        }
        
        # Add tools if available
        if tools:
            api_params["tools"] = tools
            api_params["tool_choice"] = {"type": "auto"}
        
        # Get response from Claude
        response = self.client.messages.create(**api_params)
        
        # Handle tool execution if needed
        if response.stop_reason == "tool_use" and tool_manager:
            return self._handle_tool_execution(response, api_params, tool_manager)

        # Return direct response
        return self._extract_text(response)

    @staticmethod
    def _extract_text(response) -> str:
        """
        Get the answer text out of a Claude response.

        Newer models (e.g. Claude Sonnet 5) can prepend non-text content blocks
        (like a ThinkingBlock for extended thinking) before the text block, so
        content[0] isn't reliably the answer - scan for the first text block instead.
        """
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""
    
    def _handle_tool_execution(self, initial_response, base_params: Dict[str, Any], tool_manager) -> str:
        """
        Drive up to MAX_TOOL_ROUNDS sequential rounds of tool execution, each a
        separate API request so Claude can reason about previous results before
        deciding whether to call another tool.

        Round accounting: each iteration of the loop below executes exactly one
        already-received tool_use response (the initial one on the first
        iteration) and then makes one more `messages.create` call. That new
        call includes `tools` only if another round is still allowed - so a
        query needing 2 rounds makes 3 API calls total (round 1 call already
        made by generate_response, round 2 call with tools still attached,
        then a forced call with no tools to guarantee a final text answer if
        round 2 also requested a tool). A tool execution failure is not
        raised - it's turned into an error tool_result so Claude gets one
        more turn to compose a graceful answer instead of the request
        crashing.

        Args:
            initial_response: The response containing the first round's tool use requests
            base_params: Base API parameters (including "tools"/"tool_choice" if any were passed)
            tool_manager: Manager to execute tools

        Returns:
            Final response text after all tool execution rounds
        """
        messages = base_params["messages"].copy()
        response = initial_response
        rounds_used = 0

        while True:
            messages.append({"role": "assistant", "content": response.content})

            tool_results, had_error = self._execute_tool_blocks(response, tool_manager)
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            rounds_used += 1

            more_rounds_allowed = rounds_used < self.MAX_TOOL_ROUNDS and not had_error

            next_params = {
                **self.base_params,
                "messages": messages,
                "system": base_params["system"]
            }
            if more_rounds_allowed and "tools" in base_params:
                next_params["tools"] = base_params["tools"]
                next_params["tool_choice"] = base_params.get("tool_choice", {"type": "auto"})

            response = self.client.messages.create(**next_params)

            if response.stop_reason != "tool_use":
                return self._extract_text(response)

            if not more_rounds_allowed:
                # The call above already omitted tools, so a real provider
                # cannot legally return tool_use here - defensive fallback
                # only, to guarantee we never return an empty response.
                return self._extract_text(response) or "I wasn't able to complete that request."

    @staticmethod
    def _execute_tool_blocks(response, tool_manager):
        """
        Execute every tool_use block in a response.

        A failing tool call is not raised - it's caught and turned into an
        error tool_result so Claude can see what happened and compose a
        graceful final answer instead of the request crashing outright.

        Returns:
            Tuple of (tool_results list, had_error bool)
        """
        tool_results = []
        had_error = False
        for content_block in response.content:
            if content_block.type != "tool_use":
                continue
            try:
                tool_result = tool_manager.execute_tool(
                    content_block.name,
                    **content_block.input
                )
            except Exception as exc:
                tool_result = f"Tool execution failed: {exc}"
                had_error = True
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": content_block.id,
                "content": tool_result
            })
        return tool_results, had_error