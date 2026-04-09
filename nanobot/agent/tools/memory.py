"""Memory tools for ReMe integration.

These tools allow the LLM to:
- Retrieve memories from long-term storage (semantic search)
- Add new memories when important information is shared
- List recent memories to understand what's stored
- Get memory system status for debugging

The LLM decides when to use these tools, rather than automatic retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.reme_adapter import RemeMemoryAdapter


# Default user name getter
def _default_get_user_name() -> str:
    """Default implementation returns 'default_user'."""
    return "default_user"


# ---------------------------------------------------------------------------
# retrieve_memory
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema(
            "Search query to find relevant memories. Use keywords, topics, or questions."
        ),
        top_k=IntegerSchema(
            5,
            description="Maximum number of memories to return (default 5, max 20)",
            minimum=1,
            maximum=20,
        ),
        required=["query"],
    )
)
class RetrieveMemoryTool(Tool):
    """Retrieve memories from long-term storage using semantic search.

    WHEN TO USE:
    - User mentions "before", "last time", "remember", "previously"
    - Need to recall user preferences, habits, or project context
    - User asks about past conversations or stored information
    - Uncertain if relevant information exists in memory

    WHEN NOT TO USE:
    - Simple greetings like "hello", "hi"
    - General questions not related to user's personal context
    - User explicitly asks to ignore past context

    Note: Retrieval takes a few seconds. Only call when genuinely needed.
    """

    def __init__(self, adapter: RemeMemoryAdapter, get_user_name: Callable[[], str] = _default_get_user_name):
        self._adapter = adapter
        self._get_user_name = get_user_name

    @property
    def name(self) -> str:
        return "retrieve_memory"

    @property
    def description(self) -> str:
        return (
            "Search your long-term memory for stored information about the user. "
            "This is the PRIMARY way to recall: user preferences, names, past conversations, "
            "relationships, habits, and any facts previously mentioned. "
            "Use this tool whenever the user asks about something they told you before, "
            "or when context from previous conversations would be helpful. "
            "Do NOT use read_file/grep to search memory files - use this tool instead."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, query: str, top_k: int = 5, **kwargs: Any) -> str:
        if not self._adapter.is_healthy():
            status = self._adapter.get_status()
            return (
                f"Memory system is currently unavailable. "
                f"Status: {status.get('last_error', 'circuit breaker open')}"
            )

        try:
            user_id = self._get_user_name()
            result = await self._adapter.retrieve_memory(query, user_id=user_id, top_k=top_k)
            if not result:
                return "No relevant memories found."
            return result
        except Exception as e:
            return f"Error retrieving memories: {str(e)}"


# ---------------------------------------------------------------------------
# add_memory
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        content=StringSchema(
            "The information to store in long-term memory. Be specific and clear."
        ),
        category=StringSchema(
            "Category of the memory: personal, project, preference, or general (default: general)"
        ),
        required=["content"],
    )
)
class AddMemoryTool(Tool):
    """Add important information to long-term memory.

    WHEN TO USE:
    - User explicitly says "remember this", "note this down"
    - User shares personal information (name, age, location, job)
    - User states preferences or habits (likes, dislikes, routines)
    - Important decisions or agreements are made
    - Project-specific information is discussed

    WHEN NOT TO USE:
    - Casual conversation without important facts
    - Temporary information or quick questions
    - Information the user wants to keep private/forget

    Be selective - only store genuinely important information.
    """

    def __init__(self, adapter: RemeMemoryAdapter, get_user_name: Callable[[], str] = _default_get_user_name):
        self._adapter = adapter
        self._get_user_name = get_user_name

    @property
    def name(self) -> str:
        return "add_memory"

    @property
    def description(self) -> str:
        return (
            "Store important information into your long-term memory. "
            "Use this tool when: user shares personal info (name, age, location, job), "
            "user tells you preferences or habits, user says 'remember this' or 'note this down', "
            "important decisions or agreements are made. "
            "Do NOT write to memory files directly - use this tool instead."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, content: str, category: str = "general", **kwargs: Any) -> str:
        if not self._adapter.is_healthy():
            status = self._adapter.get_status()
            return (
                f"Memory system is currently unavailable. "
                f"Status: {status.get('last_error', 'circuit breaker open')}"
            )

        try:
            # Add category prefix to help with organization
            if category and category != "general":
                formatted_content = f"[{category}] {content}"
            else:
                formatted_content = content

            user_id = self._get_user_name()
            node = await self._adapter.add_memory(formatted_content, user_id=user_id)
            if node:
                return f"Memory stored successfully for {user_id} (ID: {node.memory_id[:8]}...)"
            return "Failed to store memory."
        except Exception as e:
            return f"Error storing memory: {str(e)}"


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        limit=IntegerSchema(
            10,
            description="Maximum number of recent memories to list (default 10, max 50)",
            minimum=1,
            maximum=50,
        ),
    )
)
class ListMemoriesTool(Tool):
    """List recent memories from long-term storage.

    WHEN TO USE:
    - User asks "what do you remember", "what do you know about me"
    - Need to quickly see what information is stored
    - Debugging memory-related questions

    Returns the most recently added memories.
    """

    def __init__(self, adapter: RemeMemoryAdapter, get_user_name: Callable[[], str] = _default_get_user_name):
        self._adapter = adapter
        self._get_user_name = get_user_name

    @property
    def name(self) -> str:
        return "list_memories"

    @property
    def description(self) -> str:
        return (
            "List all memories stored in your long-term memory. "
            "This is the PRIMARY way to see what you know about the user. "
            "Use when: user asks 'what do you remember about me', you need to review "
            "stored information, or before using retrieve_memory to understand what's available. "
            "Do NOT read memory files directly - use this tool instead."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, limit: int = 10, **kwargs: Any) -> str:
        if not self._adapter.is_healthy():
            status = self._adapter.get_status()
            return (
                f"Memory system is currently unavailable. "
                f"Status: {status.get('last_error', 'circuit breaker open')}"
            )

        try:
            user_id = self._get_user_name()
            memories = await self._adapter.list_memories(user_id=user_id, limit=limit)
            if not memories:
                return "No memories stored yet."

            lines = [f"## Stored Memories ({len(memories)} items)\n"]
            for i, m in enumerate(memories, 1):
                # Truncate long content
                content = m.content[:100] + "..." if len(m.content) > 100 else m.content
                memory_id = m.memory_id[:8]
                lines.append(f"{i}. `{memory_id}` {content}")

            return "\n".join(lines)
        except Exception as e:
            return f"Error listing memories: {str(e)}"


# ---------------------------------------------------------------------------
# get_memory_status
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema()
)
class GetMemoryStatusTool(Tool):
    """Get the current status of the memory system.

    WHEN TO USE:
    - Debugging memory-related issues
    - User asks if memory system is working
    - Checking after memory-related errors

    Returns health status, circuit breaker state, and recent errors.
    """

    def __init__(self, adapter: RemeMemoryAdapter):
        self._adapter = adapter

    @property
    def name(self) -> str:
        return "get_memory_status"

    @property
    def description(self) -> str:
        return (
            "Check the status of the memory system. "
            "Use for debugging or when user asks if memory is working properly."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        status = self._adapter.get_status()

        lines = ["## Memory System Status\n"]
        lines.append(f"- **Started**: {'Yes' if status['started'] else 'No'}")
        lines.append(f"- **Healthy**: {'Yes' if status['healthy'] else 'No'}")
        lines.append(f"- **Circuit Breaker**: {'Open' if status['circuit_open'] else 'Closed'}")
        lines.append(f"- **Failure Count**: {status['failure_count']}/{self._adapter.MAX_FAILURES}")

        if status.get('last_error'):
            lines.append(f"- **Last Error**: {status['last_error']}")

        if status.get('last_failure_time'):
            from datetime import datetime
            ts = datetime.fromtimestamp(status['last_failure_time'])
            lines.append(f"- **Last Failure**: {ts.strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# delete_memory
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        memory_id=StringSchema(
            "The ID of the memory to delete (8-character prefix is sufficient)"
        ),
        required=["memory_id"],
    )
)
class DeleteMemoryTool(Tool):
    """Delete a specific memory from long-term storage.

    WHEN TO USE:
    - User explicitly asks to "forget" or "delete" specific information
    - Stored information is outdated or incorrect

    Use list_memories first to find the memory ID if needed.
    """

    def __init__(self, adapter: RemeMemoryAdapter):
        self._adapter = adapter

    @property
    def name(self) -> str:
        return "delete_memory"

    @property
    def description(self) -> str:
        return (
            "Delete a specific memory by its ID. "
            "Use when user wants to forget specific information. "
            "Use list_memories to find memory IDs."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, memory_id: str, **kwargs: Any) -> str:
        if not self._adapter.is_healthy():
            status = self._adapter.get_status()
            return (
                f"Memory system is currently unavailable. "
                f"Status: {status.get('last_error', 'circuit breaker open')}"
            )

        try:
            # Try to find full memory ID from prefix
            memories = await self._adapter.list_memories(limit=100)
            matching = [m for m in memories if m.memory_id.startswith(memory_id)]

            if not matching:
                return f"Memory not found with ID: {memory_id}"

            if len(matching) > 1:
                return f"Multiple memories match ID prefix '{memory_id}'. Please be more specific."

            full_id = matching[0].memory_id
            success = await self._adapter.delete_memory(full_id)

            if success:
                return f"Memory deleted successfully (ID: {full_id[:8]}...)"
            return f"Failed to delete memory."
        except Exception as e:
            return f"Error deleting memory: {str(e)}"


# ---------------------------------------------------------------------------
# Tool registration helper
# ---------------------------------------------------------------------------


def register_memory_tools(
    registry: Any,
    adapter: RemeMemoryAdapter,
    get_user_name: Callable[[], str] = _default_get_user_name
) -> None:
    """Register all memory tools with the given registry.

    Args:
        registry: ToolRegistry instance
        adapter: RemeMemoryAdapter instance
        get_user_name: Callable that returns the current user's name for memory attribution
    """
    registry.register(RetrieveMemoryTool(adapter, get_user_name))
    registry.register(AddMemoryTool(adapter, get_user_name))
    registry.register(ListMemoriesTool(adapter, get_user_name))
    registry.register(GetMemoryStatusTool(adapter))
    registry.register(DeleteMemoryTool(adapter))