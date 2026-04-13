"""Async dual-perspective memory writer with fallback retry queue."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.soul.memory_config import MemoryPalaceBridge


@dataclass
class WriteTask:
    """A pending (or retry-able) memory write task."""

    wing: str
    room: str
    content: str
    metadata: dict[str, Any]
    retries: int = 0


class MemoryWriter:
    """Async dual-perspective memory writer."""

    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5
    QUEUE_MAX_SIZE: int = 100

    def __init__(self, bridge: MemoryPalaceBridge) -> None:
        self.bridge = bridge
        self._retry_queue: list[WriteTask] = []

    async def write_dual(self, user_msg: str, ai_msg: str, timestamp: str) -> None:
        """Non-blocking dual-perspective write. Failures enter retry queue."""
        # Clean up excessive blank lines from chat content
        user_msg = _collapse_blank_lines(user_msg)
        ai_msg = _collapse_blank_lines(ai_msg)

        raw_dialog = f"[用户] {user_msg}\n[{self.bridge.ai_wing}] {ai_msg}"

        tasks = [
            WriteTask(
                wing=self.bridge.ai_wing,
                room="daily",
                content=(
                    f"## 刚才的对话\n{raw_dialog}\n\n"
                    f"## 我的感受\n"
                    f"（这段感受将在 Dream 时被细细品味和归类）"
                ),
                metadata={"timestamp": timestamp, "digestion_status": "active"},
            ),
            WriteTask(
                wing=self.bridge.user_wing,
                room="daily",
                content=(
                    f"## 刚才的对话\n{raw_dialog}\n\n"
                    f"## 我观察到的关于对方\n"
                    f"（这些观察将在 Dream 时被细细品味和归类）"
                ),
                metadata={"timestamp": timestamp, "digestion_status": "active"},
            ),
        ]

        results = await asyncio.gather(
            *[self._try_write(t) for t in tasks],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                task = getattr(result, "_write_task", None)
                if task:
                    await self._enqueue_retry(task)

    async def _try_write(self, task: WriteTask) -> None:
        """Single write attempt. Raises on failure."""
        try:
            success = await self.bridge.add_drawer(
                wing=task.wing,
                room=task.room,
                content=task.content,
                metadata=task.metadata,
            )
            if not success:
                raise RuntimeError(f"add_drawer returned False: wing={task.wing}")
        except Exception as e:
            e._write_task = task  # type: ignore[attr-defined]
            raise

    async def _enqueue_retry(self, task: WriteTask) -> None:
        """Enqueue failed write for retry. Discard if max retries exceeded."""
        task.retries += 1
        if task.retries > self.MAX_RETRIES:
            logger.error(
                "Memory write ultimately failed, discarding: wing={}, retries={}",
                task.wing,
                task.retries,
            )
            return
        while len(self._retry_queue) >= self.QUEUE_MAX_SIZE:
            self._retry_queue.pop(0)
            logger.warning("Memory retry queue full, dropping oldest entry")
        self._retry_queue.append(task)

    async def retry_loop(self) -> None:
        """Background loop to process retry queue."""
        while True:
            if self._retry_queue:
                task = self._retry_queue.pop(0)
                try:
                    await self._try_write(task)
                    logger.info("Memory retry write succeeded: wing={}", task.wing)
                except Exception:
                    await self._enqueue_retry(task)
            await asyncio.sleep(self.RETRY_DELAY)


def _collapse_blank_lines(text: str) -> str:
    """将连续多个空行压缩为单个空行，并去除首尾空白行。"""
    if not text:
        return text
    lines = text.splitlines()
    result: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank
    return "\n".join(result).strip()
