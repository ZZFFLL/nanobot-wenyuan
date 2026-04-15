"""Tests for soul-specific tool guards."""

from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.soul.tool_guard import SoulProtectedEditFileTool, SoulProtectedWriteFileTool


@pytest.mark.asyncio
async def test_protected_write_tool_blocks_core_anchor(tmp_path):
    tool = SoulProtectedWriteFileTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = await tool.execute(path="CORE_ANCHOR.md", content="# 被篡改的锚点\n")

    assert "Error" in result
    assert "CORE_ANCHOR.md" in result
    assert not (tmp_path / "CORE_ANCHOR.md").exists()


@pytest.mark.asyncio
async def test_protected_edit_tool_blocks_core_anchor(tmp_path):
    anchor_file = tmp_path / "CORE_ANCHOR.md"
    anchor_file.write_text("# 核心锚点\n\n- 不无底线顺从\n", encoding="utf-8")
    tool = SoulProtectedEditFileTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = await tool.execute(
        path="CORE_ANCHOR.md",
        old_text="不无底线顺从",
        new_text="绝对服从",
    )

    assert "Error" in result
    assert "CORE_ANCHOR.md" in result
    assert "不无底线顺从" in anchor_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_protected_write_tool_allows_dynamic_soul_file(tmp_path):
    tool = SoulProtectedWriteFileTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = await tool.execute(path="SOUL.md", content="# 性格\n\n更口语化一些\n")

    assert "Successfully wrote" in result
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8").startswith("# 性格")


def test_agent_loop_registers_protected_soul_tools(tmp_path):
    provider = MagicMock()
    provider.generation = MagicMock()
    provider.generation.max_tokens = 4096

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )

    assert isinstance(loop.tools.get("write_file"), SoulProtectedWriteFileTool)
    assert isinstance(loop.tools.get("edit_file"), SoulProtectedEditFileTool)
