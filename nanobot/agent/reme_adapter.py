"""ReMe memory adapter for nanobot integration.

This adapter bridges nanobot's memory system with ReMe's vector-based memory.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.reme_loader import RemeConfig
    from nanobot.providers.base import LLMProvider
    from reme import ReMe
    from reme.core.schema import MemoryNode


class RemeMemoryAdapter:
    """
    Bridges nanobot and ReMe vector memory system.

    Provides MemoryStore-compatible interface, internally using ReMe vector storage.

    Error Handling:
    - Circuit breaker pattern: stops retries after repeated failures
    - Graceful degradation: falls back to empty result on failure
    - Clear error logging: tracks last error and failure count for debugging

    Dead Loop Protection:
    - Global retrieval lock: prevents concurrent retrievals
    - Min interval: prevents rapid-fire retrievals (5 seconds)
    - Max retrievals per minute: prevents infinite loops (10 retrievals)
    - Recursive detection: detects when retrieval is called during retrieval

    Important:
    - ReMe retrieval is a complex multi-phase process involving multiple LLM calls
    - Typical retrieval takes 30-60 seconds for semantic search + temporal filtering
    - Do NOT use short timeouts - let ReMe complete its retrieval strategy
    """

    # Circuit breaker thresholds
    MAX_FAILURES = 3  # After this many failures, circuit opens
    RECOVERY_TIMEOUT = 60  # Seconds before attempting recovery

    # Dead loop protection
    MIN_RETRIEVAL_INTERVAL = 5.0  # Minimum seconds between retrievals
    MAX_RETRIEVALS_PER_MINUTE = 10  # Maximum retrievals in 60 second window

    # Note: ReMe retrieval takes 30-60s, no timeout on retrieval operations
    # Only use timeout for explicit async operations in sync context

    def __init__(
        self,
        workspace: Path,
        config: "RemeConfig",
        provider: "LLMProvider",
    ):
        self.workspace = workspace
        self.config = config
        self.provider = provider
        self._reme: "ReMe | None" = None
        self._started = False
        self._lock = asyncio.Lock()

        # Profile file paths (compatible with existing files)
        self.soul_file = workspace / config.profile.soul_file
        self.user_file = workspace / config.profile.user_file
        self.memory_file = workspace / config.profile.memory_file
        self.history_file = workspace / "memory" / "history.jsonl"

        # User ID (for Personal Memory)
        self._default_user_id = "default_user"

        # Circuit breaker state
        self._healthy = True
        self._failure_count = 0
        self._last_error: str | None = None
        self._last_failure_time: float | None = None
        self._circuit_open = False

        # Dead loop protection state
        self._retrieval_in_progress = False
        self._last_retrieval_time: float = 0.0
        self._retrieval_times: list[float] = []  # Track recent retrieval times

    # =========================================================================
    # Circuit breaker and error handling
    # =========================================================================

    def _check_dead_loop(self) -> tuple[bool, str]:
        """
        Check for potential dead loop conditions.

        Returns:
            Tuple of (should_skip: bool, reason: str)
        """
        now = time.time()

        # 1. Check for recursive retrieval (retrieval called during retrieval)
        if self._retrieval_in_progress:
            reason = "Recursive retrieval detected - retrieval already in progress"
            logger.error(f"DEAD LOOP PREVENTED: {reason}")
            return True, reason

        # 2. Check minimum interval between retrievals
        elapsed = now - self._last_retrieval_time
        if elapsed < self.MIN_RETRIEVAL_INTERVAL:
            reason = f"Too soon since last retrieval ({elapsed:.1f}s < {self.MIN_RETRIEVAL_INTERVAL}s)"
            logger.warning(f"Rate limited: {reason}")
            return True, reason

        # 3. Check max retrievals per minute
        # Clean up old entries (older than 60 seconds)
        self._retrieval_times = [t for t in self._retrieval_times if now - t < 60.0]
        if len(self._retrieval_times) >= self.MAX_RETRIEVALS_PER_MINUTE:
            reason = f"Too many retrievals ({len(self._retrieval_times)} in last minute)"
            logger.error(f"DEAD LOOP PREVENTED: {reason}")
            # Force open circuit breaker
            self._circuit_open = True
            self._healthy = False
            self._last_error = reason
            self._last_failure_time = now
            return True, reason

        return False, ""

    def _begin_retrieval(self) -> None:
        """Mark retrieval as started."""
        self._retrieval_in_progress = True
        self._last_retrieval_time = time.time()
        self._retrieval_times.append(self._last_retrieval_time)

    def _end_retrieval(self) -> None:
        """Mark retrieval as ended."""
        self._retrieval_in_progress = False

    def _record_failure(self, error: Exception, operation: str) -> None:
        """Record a failure and update circuit breaker state."""
        self._failure_count += 1
        self._last_error = f"{operation}: {type(error).__name__}: {error}"
        self._last_failure_time = time.time()

        logger.warning(
            f"ReMe operation failed ({self._failure_count}/{self.MAX_FAILURES}): {self._last_error}"
        )

        # Open circuit breaker after max failures
        if self._failure_count >= self.MAX_FAILURES:
            self._circuit_open = True
            self._healthy = False
            logger.error(
                f"ReMe circuit breaker OPENED after {self._failure_count} failures. "
                f"Will attempt recovery after {self.RECOVERY_TIMEOUT}s. "
                f"Last error: {self._last_error}"
            )

    def _check_circuit(self) -> bool:
        """Check if circuit breaker allows operation."""
        if not self._circuit_open:
            return True

        # Check if recovery timeout has passed
        if self._last_failure_time is None:
            return True

        elapsed = time.time() - self._last_failure_time
        if elapsed >= self.RECOVERY_TIMEOUT:
            logger.info(
                f"ReMe circuit breaker attempting recovery after {elapsed:.1f}s"
            )
            return True

        logger.debug(
            f"ReMe circuit breaker OPEN, skipping operation. "
            f"Recovery in {self.RECOVERY_TIMEOUT - elapsed:.1f}s"
        )
        return False

    def _record_success(self) -> None:
        """Record a successful operation and reset circuit breaker."""
        if self._failure_count > 0 or not self._healthy:
            logger.info("ReMe operation succeeded, circuit breaker RESET")
        self._failure_count = 0
        self._last_error = None
        self._circuit_open = False
        self._healthy = True

    def is_healthy(self) -> bool:
        """Check if ReMe adapter is healthy."""
        return self._healthy and self._started

    def get_status(self) -> dict:
        """Get adapter status for debugging."""
        return {
            "healthy": self._healthy,
            "started": self._started,
            "circuit_open": self._circuit_open,
            "failure_count": self._failure_count,
            "last_error": self._last_error,
            "last_failure_time": self._last_failure_time,
        }

    # =========================================================================
    # Lifecycle management
    # =========================================================================

    async def start(self) -> None:
        """Initialize ReMe memory system."""
        if self._started:
            return

        async with self._lock:
            if self._started:
                return

            try:
                from reme import ReMe

                # Build LLM config - get from provider if not in reme.yaml
                llm_config = self.config.get_effective_llm_config()

                # Get API key from provider
                if not llm_config.get("api_key"):
                    llm_config["api_key"] = getattr(self.provider, "api_key", "") or ""
                if not llm_config.get("base_url"):
                    llm_config["base_url"] = getattr(self.provider, "api_base", "") or ""

                # Get model name from provider (CRITICAL - prevents empty model)
                if not llm_config.get("model_name"):
                    llm_config["model_name"] = self.provider.get_default_model()

                # Validate required config
                if not llm_config.get("model_name"):
                    raise ValueError(
                        "LLM model_name not configured. "
                        "Set in reme.yaml or ensure provider has default model."
                    )

                # Build embedding config
                embedding_config = self.config.get_effective_embedding_config()
                if not embedding_config.get("api_key"):
                    embedding_config["api_key"] = getattr(self.provider, "api_key", "") or ""
                if not embedding_config.get("base_url"):
                    embedding_config["base_url"] = getattr(self.provider, "api_base", "") or ""

                # Validate embedding config
                if not embedding_config.get("api_key") or not embedding_config.get("base_url"):
                    raise ValueError(
                        "Embedding API not configured. "
                        "Set embedding.api_key and embedding.base_url in reme.yaml."
                    )

                # Build vector store config
                vector_store_config = self.config.get_effective_vector_store_config()

                logger.info(
                    f"ReMe LLM config: model={llm_config.get('model_name')}, "
                    f"base_url={llm_config.get('base_url')}"
                )
                logger.info(
                    f"ReMe Embedding config: model={embedding_config.get('model_name')}, "
                    f"base_url={embedding_config.get('base_url')}"
                )

                self._reme = ReMe(
                    working_dir=str(self.workspace / self.config.working_dir),
                    default_llm_config=llm_config,
                    default_embedding_model_config=embedding_config,
                    default_vector_store_config=vector_store_config,
                    enable_profile=self.config.enable_profile_files,
                )

                await self._reme.start()
                self._started = True
                self._record_success()
                logger.info(
                    f"ReMe memory system started (vector_store={self.config.vector_store_backend})"
                )

            except ImportError as e:
                logger.error(f"ReMe module not installed: {e}. Install with: pip install reme-ai")
                self._record_failure(e, "start")
                raise
            except ValueError as e:
                logger.error(f"ReMe configuration error: {e}")
                self._record_failure(e, "start")
                raise
            except Exception as e:
                self._record_failure(e, "start")
                logger.error(f"Failed to start ReMe: {e}")
                raise

    async def close(self) -> None:
        """Close ReMe memory system."""
        if self._reme and self._started:
            await self._reme.close()
            self._started = False
            logger.info("ReMe memory system closed")

    async def __aenter__(self) -> "RemeMemoryAdapter":
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    def _ensure_started(self) -> None:
        """Ensure ReMe has been started."""
        if not self._started or not self._reme:
            raise RuntimeError("ReMe not started. Call await adapter.start() first.")

    # =========================================================================
    # MemoryStore compatible interface
    # =========================================================================

    async def read_memory_async(self) -> str:
        """Async read long-term memory."""
        if not self._check_circuit():
            return ""

        try:
            memories = await self._reme.retrieve_memory(
                query="all important memories user preferences project information",
                user_name=self._default_user_id,
            )
            self._record_success()
            return memories or ""
        except Exception as e:
            self._record_failure(e, "read_memory_async")
            logger.warning(f"Failed to read memory: {e}")
            return ""

    def read_memory(self) -> str:
        """Read long-term memory (compatible with MemoryStore interface).

        Note: ReMe retrieval takes 30-60 seconds, no timeout applied.
        """
        if not self._started or not self._reme:
            return ""

        if not self._check_circuit():
            return ""

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.read_memory_async())
                    # No timeout - let ReMe complete
                    return future.result()
            else:
                return loop.run_until_complete(self.read_memory_async())
        except Exception as e:
            self._record_failure(e, "read_memory")
            logger.warning(f"Failed to read memory: {e}")
            return ""

    async def write_memory_async(self, content: str) -> None:
        """Async write long-term memory."""
        if not self._check_circuit():
            logger.warning("Circuit breaker open, skipping memory write")
            return

        try:
            await self._reme.add_memory(
                memory_content=content,
                user_name=self._default_user_id,
            )
            self._record_success()
        except Exception as e:
            self._record_failure(e, "write_memory_async")
            logger.warning(f"Failed to write memory: {e}")

    def write_memory(self, content: str) -> None:
        """Write long-term memory (compatible with MemoryStore interface)."""
        if not self._started or not self._reme:
            return

        if not self._check_circuit():
            return

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.write_memory_async(content))
            else:
                loop.run_until_complete(self.write_memory_async(content))
        except Exception as e:
            self._record_failure(e, "write_memory")
            logger.warning(f"Failed to write memory: {e}")

    def read_soul(self) -> str:
        """Read robot personality."""
        if self.soul_file.exists():
            return self.soul_file.read_text(encoding="utf-8")
        return ""

    def write_soul(self, content: str) -> None:
        """Write robot personality."""
        self.soul_file.parent.mkdir(parents=True, exist_ok=True)
        self.soul_file.write_text(content, encoding="utf-8")

    def read_user(self) -> str:
        """Read user preferences file."""
        if self.user_file.exists():
            return self.user_file.read_text(encoding="utf-8")
        return ""

    def write_user(self, content: str) -> None:
        """Write user preferences file."""
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        self.user_file.write_text(content, encoding="utf-8")

    async def get_memory_context_async(self, query: str | None = None) -> str:
        """Async get memory context for ContextBuilder.

        ReMe's retriever already implements intelligent multi-phase retrieval:
        - Phase 1: Semantic search with diverse query formulations (3-5 queries)
        - Phase 2: Temporal search (when time references detected)
        - Phase 3: History deep dive (when needed)

        We simply pass the query to ReMe and let its LLM handle the retrieval strategy.

        Error handling:
        - Dead loop protection: prevents recursive/repeated retrievals
        - Circuit breaker check before operation
        - Never throws - returns empty string on failure
        - Records failures for debugging

        Args:
            query: User's current message for semantic retrieval

        Returns:
            Formatted memory context string (empty on failure)
        """
        # Dead loop protection - CRITICAL
        should_skip, reason = self._check_dead_loop()
        if should_skip:
            logger.warning(f"Skipping memory retrieval: {reason}")
            return ""

        # Circuit breaker check - skip if circuit is open
        if not self._check_circuit():
            logger.debug("ReMe circuit breaker open, skipping memory retrieval")
            return ""

        if not query:
            query = "用户偏好 项目信息 重要记忆"

        self._begin_retrieval()
        try:
            memories = await self._reme.retrieve_memory(
                query=query,
                user_name=self._default_user_id,
                retrieve_top_k=self.config.retrieve_top_k,
            )
            self._record_success()
            if memories:
                return f"## Long-term Memory\n{memories}"
            return ""
        except Exception as e:
            self._record_failure(e, "retrieve_memory")
            # Return empty string instead of throwing - graceful degradation
            logger.warning(f"Memory retrieval failed, returning empty context: {e}")
            return ""
        finally:
            self._end_retrieval()

    def get_memory_context(self, query: str | None = None) -> str:
        """Get memory context (for ContextBuilder).

        Important:
        - ReMe retrieval is multi-phase: semantic search, temporal filtering, history deep-dive
        - Each phase involves multiple LLM calls (typically 4-5 calls)
        - Typical retrieval time: 30-60 seconds
        - NO TIMEOUT: Let ReMe complete its retrieval strategy

        Error handling:
        - Dead loop protection: prevents recursive/repeated retrievals
        - Never throws - returns empty string on any failure
        - Logs detailed error for debugging
        - Uses circuit breaker to prevent cascading failures

        Args:
            query: User's current message for semantic memory retrieval
        """
        if not self._started or not self._reme:
            logger.warning("ReMe not started, returning empty memory context")
            return ""

        # Dead loop protection - CRITICAL
        should_skip, reason = self._check_dead_loop()
        if should_skip:
            logger.warning(f"Skipping memory retrieval: {reason}")
            return ""

        # Circuit breaker check
        if not self._check_circuit():
            logger.debug("ReMe circuit breaker open, skipping memory retrieval")
            return ""

        self._begin_retrieval()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Use ThreadPoolExecutor without timeout - ReMe retrieval is complex
                # and typically takes 30-60 seconds for multi-phase retrieval
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run, self._get_memory_context_async_internal(query)
                    )
                    # No timeout - let ReMe complete its full retrieval strategy
                    # Circuit breaker will handle repeated failures
                    logger.debug(f"ReMe retrieval started for query: {query[:50] if query else 'default'}...")
                    result = future.result()
                    logger.debug(f"ReMe retrieval completed")
                    return result
            else:
                return loop.run_until_complete(self._get_memory_context_async_internal(query))
        except Exception as e:
            self._record_failure(e, "get_memory_context")
            logger.warning(f"Failed to get memory context: {e}")
            return ""
        finally:
            self._end_retrieval()

    async def _get_memory_context_async_internal(self, query: str | None = None) -> str:
        """Internal async retrieval without dead loop checks (already done by caller)."""
        if not query:
            query = "用户偏好 项目信息 重要记忆"

        try:
            memories = await self._reme.retrieve_memory(
                query=query,
                user_name=self._default_user_id,
                retrieve_top_k=self.config.retrieve_top_k,
            )
            self._record_success()
            if memories:
                return f"## Long-term Memory\n{memories}"
            return ""
        except Exception as e:
            self._record_failure(e, "retrieve_memory")
            logger.warning(f"Memory retrieval failed, returning empty context: {e}")
            return ""

    # =========================================================================
    # Core memory operations
    # =========================================================================

    async def summarize_conversation(
        self,
        messages: list[dict],
        user_id: str | None = None,
        task_name: str | None = None,
    ) -> list["MemoryNode"]:
        """
        Extract memories from conversation.

        Args:
            messages: Conversation message list
            user_id: User identifier
            task_name: Task name (for Procedural Memory)

        Returns:
            Generated memory node list
        """
        self._ensure_started()

        if not self._check_circuit():
            logger.warning("Circuit breaker open, skipping conversation summarization")
            return []

        # Convert message format
        formatted_messages = self._format_messages_for_reme(messages)

        # Build kwargs
        kwargs = {}
        kwargs["user_name"] = user_id or self._default_user_id

        if task_name and self.config.enable_procedural_memory:
            kwargs["task_name"] = task_name

        try:
            # Call ReMe summarize
            result = await self._reme.summarize_memory(
                messages=formatted_messages,
                retrieve_top_k=self.config.retrieve_top_k,
                **kwargs,
            )
            self._record_success()
            logger.info(f"Summarized {len(messages)} messages into memory")
            return result
        except Exception as e:
            self._record_failure(e, "summarize_conversation")
            logger.warning(f"Failed to summarize conversation: {e}")
            return []

    async def retrieve_memory(
        self,
        query: str,
        user_id: str | None = None,
        task_name: str | None = None,
        top_k: int | None = None,
    ) -> str:
        """
        Retrieve relevant memories.

        Args:
            query: Query text
            user_id: User identifier
            task_name: Task name
            top_k: Number of results

        Returns:
            Retrieved memory text
        """
        self._ensure_started()

        if not self._check_circuit():
            return ""

        kwargs = {
            "query": query,
            "retrieve_top_k": top_k or self.config.retrieve_top_k,
            "enable_time_filter": self.config.enable_time_filter,
        }

        kwargs["user_name"] = user_id or self._default_user_id

        if task_name:
            kwargs["task_name"] = task_name

        try:
            result = await self._reme.retrieve_memory(**kwargs)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure(e, "retrieve_memory")
            logger.warning(f"Failed to retrieve memory: {e}")
            return ""

    async def add_memory(
        self,
        content: str,
        when_to_use: str = "",
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> "MemoryNode | None":
        """
        Manually add memory.

        Args:
            content: Memory content
            when_to_use: Usage condition description
            user_id: User identifier
            metadata: Extra metadata

        Returns:
            Created memory node (None on failure)
        """
        self._ensure_started()

        if not self._check_circuit():
            return None

        try:
            result = await self._reme.add_memory(
                memory_content=content,
                when_to_use=when_to_use,
                user_name=user_id or self._default_user_id,
                **(metadata or {}),
            )
            self._record_success()
            return result
        except Exception as e:
            self._record_failure(e, "add_memory")
            logger.warning(f"Failed to add memory: {e}")
            return None

    async def list_memories(
        self,
        user_id: str | None = None,
        limit: int = 20,
    ) -> list["MemoryNode"]:
        """List all memories."""
        self._ensure_started()

        if not self._check_circuit():
            return []

        try:
            result = await self._reme.list_memory(
                user_name=user_id or self._default_user_id,
                limit=limit,
                sort_key="time_created",
                reverse=True,
            )
            self._record_success()
            return result
        except Exception as e:
            self._record_failure(e, "list_memories")
            logger.warning(f"Failed to list memories: {e}")
            return []

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete specified memory."""
        self._ensure_started()

        if not self._check_circuit():
            return False

        try:
            await self._reme.delete_memory(memory_id)
            self._record_success()
            return True
        except Exception as e:
            self._record_failure(e, "delete_memory")
            logger.warning(f"Failed to delete memory: {e}")
            return False

    async def delete_all_memories(self) -> int:
        """Delete all memories."""
        self._ensure_started()

        if not self._check_circuit():
            return 0

        try:
            # ReMe doesn't have a delete_all method, so we delete one by one
            memories = await self.list_memories(limit=1000)
            deleted_count = 0
            for memory in memories:
                if await self.delete_memory(memory.memory_id):
                    deleted_count += 1
            self._record_success()
            logger.info(f"Deleted {deleted_count} memories")
            return deleted_count
        except Exception as e:
            self._record_failure(e, "delete_all_memories")
            logger.warning(f"Failed to delete all memories: {e}")
            return 0

    # =========================================================================
    # History compatibility (retain history.jsonl support)
    # =========================================================================

    def append_history(self, entry: str) -> int:
        """
        Append history record (compatible with MemoryStore).

        Retains history.jsonl as backup, also stores to ReMe.
        """
        # 1. Write to history.jsonl (backup)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        cursor = self._next_cursor()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        record = {"cursor": cursor, "timestamp": ts, "content": entry}

        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 2. Async store to ReMe (non-blocking, graceful failure)
        if self._started and self._check_circuit():
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.add_memory(entry, when_to_use="历史记录"))
                else:
                    loop.run_until_complete(self.add_memory(entry, when_to_use="历史记录"))
            except Exception as e:
                logger.warning(f"Failed to store history in ReMe: {e}")

        return cursor

    def _next_cursor(self) -> int:
        """Get next cursor."""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    lines = [l for l in f.readlines() if l.strip()]
                    if lines:
                        last = json.loads(lines[-1])
                        return last.get("cursor", 0) + 1
            except (json.JSONDecodeError, KeyError):
                pass
        return 1

    # =========================================================================
    # Utility methods
    # =========================================================================

    def _format_messages_for_reme(self, messages: list[dict]) -> list[dict]:
        """
        Convert nanobot message format to ReMe format.

        ReMe requires:
        - role: "user" | "assistant"
        - content: str
        - time_created: str (YYYY-MM-DD HH:MM:SS)
        """
        formatted = []
        for msg in messages:
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multimodal content
                text_parts = [
                    block.get("text", "")
                    for block in content
                    if block.get("type") == "text"
                ]
                content = "\n".join(text_parts)

            if not content:
                continue

            formatted.append({
                "role": role,
                "content": content,
                "time_created": msg.get(
                    "timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ),
            })

        return formatted

    @property
    def reme(self) -> "ReMe":
        """Get underlying ReMe instance."""
        self._ensure_started()
        return self._reme

    async def reload_config(self, workspace: Path) -> None:
        """Hot reload config file."""
        from nanobot.config.reme_loader import load_reme_config

        config = load_reme_config(workspace)
        self.config = config
        logger.info("ReMe config reloaded")