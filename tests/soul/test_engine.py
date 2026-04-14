"""Tests for SoulEngine and SoulHook."""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from nanobot.soul.engine import SoulEngine, SoulHook


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock()
    provider.generation = MagicMock()
    provider.generation.max_tokens = 8192
    return provider


@pytest.fixture
def engine(workspace, mock_provider):
    return SoulEngine(workspace, mock_provider, "test-model")


class TestSoulEngine:

    def test_init_creates_heart_if_missing(self, engine, workspace):
        engine.initialize("小文", "温柔但倔强")
        assert (workspace / "HEART.md").exists()

    async def test_after_iteration_updates_heart(self, engine, mock_provider):
        engine.initialize("小文", "测试")
        # Simulate LLM returning valid Markdown
        valid_markdown = (
            "## 当前情绪\n开心\n\n"
            "## 情绪强度\n中\n\n"
            "## 关系状态\n好奇\n\n"
            "## 性格表现\n温柔\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n平稳\n\n"
            "## 当前渴望\n想聊天\n"
        )
        mock_provider.chat_with_retry.return_value = MagicMock(content=valid_markdown)

        context = MagicMock()
        context.messages = [
            {"role": "user", "content": "你好呀"},
            {"role": "assistant", "content": "你好！"},
        ]
        context.response = MagicMock(content="你好！")
        context.final_content = "你好！"

        hook = SoulHook(engine)
        await hook.after_iteration(context)

        text = engine.heart.read_text()
        assert text is not None
        assert "开心" in text

    async def test_after_iteration_empty_output_keeps_old(self, engine, mock_provider):
        engine.initialize("小文", "测试")
        old_text = engine.heart.read_text()

        # LLM returns empty string
        mock_provider.chat_with_retry.return_value = MagicMock(content="")

        context = MagicMock()
        context.messages = []
        context.response = MagicMock(content="测试")
        context.final_content = "测试"

        hook = SoulHook(engine)
        await hook.after_iteration(context)

        new_text = engine.heart.read_text()
        assert new_text == old_text

    async def test_before_iteration_injects_context(self, engine):
        engine.initialize("小文", "测试")

        context = MagicMock()
        context.messages = [{"role": "system", "content": "原system prompt"}]
        hook = SoulHook(engine)

        await hook.before_iteration(context)

        system_msg = context.messages[0]
        assert "情绪" in system_msg["content"]

    async def test_update_heart_markdown_output(self, engine, mock_provider):
        engine.initialize("小文", "测试")
        markdown_output = (
            "## 当前情绪\n感动\n\n"
            "## 情绪强度\n中偏高\n\n"
            "## 关系状态\n开始信任\n\n"
            "## 性格表现\n温柔\n\n"
            "## 情感脉络\n- 刚刚：用户很关心 → 很感动\n\n"
            "## 情绪趋势\n上升\n\n"
            "## 当前渴望\n想多说说话\n"
        )
        mock_provider.chat_with_retry.return_value = MagicMock(content=markdown_output)

        result = await engine.update_heart("你还好吗", "我很好呀")
        assert result is True
        text = engine.heart.read_text()
        assert "感动" in text

    async def test_update_heart_calls_adjudicator(self, engine, mock_provider):
        engine.initialize("小文", "测试")
        markdown_output = (
            "## 当前情绪\n开心\n\n"
            "## 情绪强度\n中\n\n"
            "## 关系状态\n好奇\n\n"
            "## 性格表现\n温柔\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n平稳\n\n"
            "## 当前渴望\n想聊天\n"
        )
        mock_provider.chat_with_retry.return_value = MagicMock(content=markdown_output)
        engine._adjudicator = MagicMock()
        engine._adjudicator.adjudicate_heart_update.return_value = (True, markdown_output)

        result = await engine.update_heart("你好", "你好呀")

        assert result is True
        engine._adjudicator.adjudicate_heart_update.assert_called_once()

    async def test_update_heart_llm_failure_keeps_old(self, engine, mock_provider):
        engine.initialize("小文", "测试")
        old_text = engine.heart.read_text()

        mock_provider.chat_with_retry.side_effect = Exception("API error")

        result = await engine.update_heart("你好", "嗨")
        assert result is False
        assert engine.heart.read_text() == old_text

    async def test_update_heart_rejects_non_markdown(self, engine, mock_provider):
        """LLM output without ## headers should be rejected."""
        engine.initialize("小文", "测试")
        old_text = engine.heart.read_text()

        # LLM returns plain text without section headers
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="I feel happy today"
        )

        result = await engine.update_heart("你好", "嗨")
        assert result is False
        assert engine.heart.read_text() == old_text

    async def test_before_iteration_no_heart_does_nothing(self, workspace, mock_provider):
        engine = SoulEngine(workspace, mock_provider, "test-model")
        # Don't initialize — no HEART.md
        context = MagicMock()
        context.messages = [{"role": "system", "content": "原prompt"}]
        hook = SoulHook(engine)

        await hook.before_iteration(context)

        assert context.messages[0]["content"] == "原prompt"

    async def test_before_iteration_with_memory_retrieval(self, engine):
        engine.initialize("小文", "测试")

        # Set up memory writer with mock bridge
        mock_bridge = MagicMock()
        mock_bridge.ai_wing = "小文"
        mock_bridge.user_wing = "用户"
        mock_bridge.search = AsyncMock(side_effect=[
            [{"text": "上次用户很累", "wing": "小文", "similarity": 0.9}],
            [{"text": "用户不喜欢被催促", "wing": "用户", "similarity": 0.85}],
        ])

        mock_writer = MagicMock()
        mock_writer.bridge = mock_bridge
        engine._memory_writer = mock_writer

        context = MagicMock()
        context.messages = [
            {"role": "system", "content": "你是小文。"},
            {"role": "user", "content": "我今天好累"},
        ]
        hook = SoulHook(engine)
        await hook.before_iteration(context)

        system_content = context.messages[0]["content"]
        assert "你想起了一些事" in system_content
        assert "你曾经历的" in system_content
        assert "你记得关于对方" in system_content

    async def test_before_iteration_memory_search_skips_short_input(self, engine):
        engine.initialize("小文", "测试")

        mock_bridge = MagicMock()
        mock_bridge.ai_wing = "小文"
        mock_bridge.user_wing = "用户"
        mock_bridge.search = AsyncMock(return_value=[])

        mock_writer = MagicMock()
        mock_writer.bridge = mock_bridge
        engine._memory_writer = mock_writer

        context = MagicMock()
        context.messages = [
            {"role": "system", "content": "你是小文。"},
            {"role": "user", "content": "hi"},  # too short (< 4 chars)
        ]
        hook = SoulHook(engine)
        await hook.before_iteration(context)

        # Should not search for such short input
        mock_bridge.search.assert_not_called()

    async def test_after_iteration_triggers_memory_write(self, engine, mock_provider):
        engine.initialize("小文", "测试")

        # Set up memory writer mock
        mock_writer = MagicMock()
        mock_writer.write_dual = AsyncMock()
        engine._memory_writer = mock_writer

        valid_markdown = (
            "## 当前情绪\n开心\n\n"
            "## 情绪强度\n中\n\n"
            "## 关系状态\n好奇\n\n"
            "## 性格表现\n温柔\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n平稳\n\n"
            "## 当前渴望\n想聊天\n"
        )
        mock_provider.chat_with_retry.return_value = MagicMock(content=valid_markdown)

        context = MagicMock()
        context.messages = [
            {"role": "user", "content": "你好呀"},
            {"role": "assistant", "content": "你好！"},
        ]
        context.response = MagicMock(content="你好！")
        context.final_content = "你好！"

        hook = SoulHook(engine)
        await hook.after_iteration(context)

        # Give the asyncio.create_task a chance to run
        await asyncio.sleep(0.1)
        mock_writer.write_dual.assert_called_once_with(
            "你好呀", "你好！", mock_writer.write_dual.call_args[0][2]
        )


class TestSoulHookIsAgentHook:

    def test_soul_hook_extends_agent_hook(self):
        from nanobot.agent.hook import AgentHook
        assert issubclass(SoulHook, AgentHook)
