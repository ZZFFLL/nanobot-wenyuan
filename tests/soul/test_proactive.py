"""Tests for ProactiveEngine."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.soul.proactive import ProactiveDecision, ProactiveEngine, _extract_section
from nanobot.soul.soul_config import SoulJsonConfig


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
    return ProactiveEngine(workspace, mock_provider, "test-model")


@pytest.fixture
def initialized_engine(engine, workspace):
    from nanobot.soul.heart import HeartManager

    hm = HeartManager(workspace)
    hm.initialize("小文", "温柔")
    return engine


class TestExtractSection:

    def test_extract_existing_section(self):
        text = "## 当前情绪\n开心\n\n## 情绪强度\n中\n"
        assert _extract_section(text, "当前情绪") == "开心"

    def test_extract_missing_section(self):
        text = "## 当前情绪\n开心\n\n## 情绪强度\n中\n"
        assert _extract_section(text, "不存在") == ""

    def test_extract_multiline_section(self):
        text = "## 情感脉络\n- 事件A → 开心\n- 事件B → 难过\n\n## 当前渴望\n想聊天\n"
        result = _extract_section(text, "情感脉络")
        assert "事件A" in result
        assert "事件B" in result


class TestGate:

    def test_no_heart_fails_gate(self, engine):
        allowed, reason = engine.check_gate()
        assert allowed is False
        assert "HEART.md 不存在" in reason

    def test_disabled_config_fails_gate(self, workspace, mock_provider):
        config = SoulJsonConfig()
        config.proactive.enabled = False
        engine = ProactiveEngine(workspace, mock_provider, "test-model", soul_config=config)
        allowed, reason = engine.check_gate()
        assert allowed is False
        assert "主动行为已禁用" in reason

    def test_should_reach_out_returns_bool(self, initialized_engine):
        assert isinstance(initialized_engine.should_reach_out(), bool)


class TestIntervals:

    def test_no_heart_returns_max_interval(self, engine):
        assert engine.get_interval_seconds() == engine.constraints.max_interval_s

    def test_high_intensity_shortens_interval(self, engine, workspace):
        from nanobot.soul.heart import HeartManager

        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔")
        baseline = engine.get_interval_seconds()
        hm.write_text(
            "## 当前情绪\n很想用户\n\n"
            "## 情绪强度\n高\n\n"
            "## 关系状态\n依赖\n\n"
            "## 性格表现\n粘人\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n焦虑\n\n"
            "## 当前渴望\n用户来找我\n"
        )
        assert engine.get_interval_seconds() < baseline

    def test_low_intensity_lengthens_interval(self, engine, workspace):
        from nanobot.soul.heart import HeartManager

        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔")
        baseline = engine.get_interval_seconds()
        hm.write_text(
            "## 当前情绪\n平静\n\n"
            "## 情绪强度\n低\n\n"
            "## 关系状态\n熟悉\n\n"
            "## 性格表现\n独立\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n平稳\n\n"
            "## 当前渴望\n没什么特别的\n"
        )
        assert engine.get_interval_seconds() > baseline


class TestDecisionFlow:

    @pytest.mark.asyncio
    async def test_decide_and_generate_returns_decision(self, initialized_engine, mock_provider):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content='{"want_to_reach_out": true, "tone": "想念且克制", "message": "今天过得怎么样？", "reason": "最近互动变少了"}'
        )

        decision = await initialized_engine.decide_and_generate()

        assert isinstance(decision, ProactiveDecision)
        assert decision.want_to_reach_out is True
        assert "今天过得怎么样" in decision.message

    @pytest.mark.asyncio
    async def test_generate_message_returns_none_on_empty_message(self, initialized_engine, mock_provider):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content='{"want_to_reach_out": false, "tone": "平静", "message": "", "reason": "现在适合安静"}'
        )

        result = await initialized_engine.generate_message()

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_message_returns_message_when_allowed(self, initialized_engine, mock_provider):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content='{"want_to_reach_out": true, "tone": "轻松分享", "message": "我刚刚想到你了", "reason": "情绪强度偏高"}'
        )

        result = await initialized_engine.generate_message()

        assert result == "我刚刚想到你了"


class TestDecisionParsing:

    def test_parse_decision_from_code_block(self):
        decision = ProactiveEngine._parse_decision(
            '```json\n{"want_to_reach_out": true, "tone": "轻松", "message": "你好呀", "reason": "想念"}\n```'
        )

        assert isinstance(decision, ProactiveDecision)
        assert decision.message == "你好呀"

    def test_decision_markdown_trace(self):
        decision = ProactiveDecision(
            want_to_reach_out=True,
            tone="想念且克制",
            message="今天过得怎么样？",
            reason="最近互动频率下降",
        )

        content = decision.to_markdown()

        assert "# 主动陪伴记录" in content
        assert "今天过得怎么样？" in content
