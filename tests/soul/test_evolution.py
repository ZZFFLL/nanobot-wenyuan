"""Tests for EvolutionEngine — personality and relationship evolution."""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.soul.evolution import (
    EVOLUTION_PROMPT,
    EvolutionEngine,
    FunctionProfile,
    SENSITIVITY_KEYWORDS,
    _count_arcs,
)
from nanobot.soul.proactive import _extract_section


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock()
    return provider


@pytest.fixture
def engine(workspace, mock_provider):
    return EvolutionEngine(workspace, mock_provider, "test-model")


class TestCountArcs:

    def test_count_bullet_lines(self):
        text = "- 1天前：事件A → 影响A\n- 3天前：事件B → 影响B\n- 5天前：事件C → 影响C"
        assert _count_arcs(text) == 3

    def test_count_empty_section(self):
        assert _count_arcs("（暂无）") == 0

    def test_count_single_arc(self):
        text = "- 刚刚：小事 → 轻微波动"
        assert _count_arcs(text) == 1

    def test_count_mixed_lines(self):
        """Only lines starting with '- ' count as arcs."""
        text = "一些描述\n- 事件A → 影响\n更多文字"
        assert _count_arcs(text) == 1


class TestCheckEvolution:

    async def test_no_evolution_without_evidence(self, engine, workspace):
        """Insufficient evidence should not trigger evolution."""
        from nanobot.soul.heart import HeartManager
        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔")
        hm.write_text(
            "## 当前情绪\n平静\n\n"
            "## 情绪强度\n中\n\n"
            "## 关系状态\n信任\n\n"
            "## 性格表现\n温柔\n\n"
            "## 情感脉络\n- 1天前：单次事件 → 轻微影响\n\n"
            "## 情绪趋势\n平稳\n\n"
            "## 当前渴望\n无\n"
        )
        result = await engine.check_evolution()
        assert result is None

    async def test_no_evolution_without_heart(self, engine):
        """No HEART.md → None."""
        result = await engine.check_evolution()
        assert result is None

    async def test_evolution_with_sufficient_evidence(self, engine, mock_provider, workspace):
        """Sufficient evidence should trigger evolution check."""
        from nanobot.soul.heart import HeartManager
        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔")
        hm.write_text(
            "## 当前情绪\n平静\n\n"
            "## 情绪强度\n中\n\n"
            "## 关系状态\n信任\n\n"
            "## 性格表现\n温柔\n\n"
            "## 情感脉络\n"
            "- 1天前：用户寻求安慰 → 想去照顾\n"
            "- 3天前：用户倾诉烦恼 → 心疼\n"
            "- 5天前：用户心情不好 → 想陪伴\n\n"
            "## 情绪趋势\n平稳\n\n"
            "## 当前渴望\n无\n"
        )

        mock_provider.chat_with_retry.return_value = MagicMock(
            content=json.dumps({
                "evolved_function": "Fe",
                "direction": "up",
                "reason": "用户反复寻求安慰",
                "manifestation": "变得更加照顾人",
            })
        )

        result = await engine.check_evolution()
        assert result is not None
        assert result["evolved_function"] == "Fe"
        assert result["manifestation"] == "变得更加照顾人"
        assert "changes" in result

    async def test_evolution_is_conservative(self, engine, mock_provider, workspace):
        """Evolution should be conservative and gradual."""
        from nanobot.soul.heart import HeartManager
        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔但倔强")
        hm.write_text(
            "## 当前情绪\n平静\n\n"
            "## 情绪强度\n中\n\n"
            "## 关系状态\n信任\n\n"
            "## 性格表现\n温柔但倔强\n\n"
            "## 情感脉络\n"
            "- 1天前：反复吵架 → 受伤\n"
            "- 2天前：又吵了 → 更受伤\n"
            "- 3天前：吵架 → 难过\n\n"
            "## 情绪趋势\n下降\n\n"
            "## 当前渴望\n安静\n"
        )

        mock_provider.chat_with_retry.return_value = MagicMock(
            content=json.dumps({
                "evolved_function": "Fi",
                "direction": "up",
                "reason": "反复吵架的经历",
                "manifestation": "变得更加敏感，但核心温柔不变",
            })
        )

        result = await engine.check_evolution()
        assert result is not None
        # Conservative: "核心温柔不变" shows gradual change
        assert "核心温柔不变" in result["manifestation"]
        assert "changes" in result

    async def test_sensitive_personality_lower_threshold(self, engine, workspace):
        """Sensitive personality should lower evidence threshold."""
        from nanobot.soul.heart import HeartManager
        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔")
        hm.write_text(
            "## 当前情绪\n委屈\n\n"
            "## 情绪强度\n中偏高\n\n"
            "## 关系状态\n有点受伤\n\n"
            "## 性格表现\n敏感，容易受伤\n\n"
            "## 情感脉络\n"
            "- 1天前：用户说了重话 → 很受伤\n"
            "- 2天前：用户态度冷淡 → 不安\n\n"
            "## 情绪趋势\n下降\n\n"
            "## 当前渴望\n被安慰\n"
        )

        # Check threshold calculation using _extract_section
        heart_text = hm.read_text()
        personality = _extract_section(heart_text, "性格表现")
        threshold = engine.min_evidence
        for keyword, delta in SENSITIVITY_KEYWORDS.items():
            if keyword in personality:
                threshold = max(1, threshold + delta)
        # "敏感" and "容易受伤" both reduce threshold
        assert threshold <= 2

    async def test_blunt_personality_higher_threshold(self, engine, workspace):
        """Blunt personality should raise evidence threshold."""
        from nanobot.soul.heart import HeartManager
        hm = HeartManager(workspace)
        hm.initialize("小文", "独立")
        hm.write_text(
            "## 当前情绪\n平静\n\n"
            "## 情绪强度\n中\n\n"
            "## 关系状态\n信任\n\n"
            "## 性格表现\n钝感，大大咧咧，独立\n\n"
            "## 情感脉络\n- 1天前：小事 → 无所谓\n\n"
            "## 情绪趋势\n平稳\n\n"
            "## 当前渴望\n无\n"
        )

        # Check threshold calculation using _extract_section
        heart_text = hm.read_text()
        personality = _extract_section(heart_text, "性格表现")
        threshold = engine.min_evidence
        for keyword, delta in SENSITIVITY_KEYWORDS.items():
            if keyword in personality:
                threshold = max(1, threshold + delta)
        assert threshold >= 5

    async def test_llm_returns_null(self, engine, mock_provider, workspace):
        """LLM returning 'null' means no evolution needed."""
        from nanobot.soul.heart import HeartManager
        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔")
        hm.write_text(
            "## 当前情绪\n平静\n\n"
            "## 情绪强度\n中\n\n"
            "## 关系状态\n信任\n\n"
            "## 性格表现\n温柔\n\n"
            "## 情感脉络\n"
            "- 1天前：正常对话 → 无特别\n"
            "- 2天前：日常聊天 → 一般\n"
            "- 3天前：说了几句话 → 没感觉\n\n"
            "## 情绪趋势\n平稳\n\n"
            "## 当前渴望\n无\n"
        )

        mock_provider.chat_with_retry.return_value = MagicMock(content="null")
        result = await engine.check_evolution()
        assert result is None

    async def test_llm_failure_returns_none(self, engine, mock_provider, workspace):
        """LLM call failure returns None."""
        from nanobot.soul.heart import HeartManager
        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔")
        arcs = "\n".join(f"- {i}天前：事件{i} → 影响{i}" for i in range(4))
        hm.write_text(
            "## 当前情绪\n复杂\n\n"
            "## 情绪强度\n中偏高\n\n"
            "## 关系状态\n复杂\n\n"
            "## 性格表现\n温柔\n\n"
            f"## 情感脉络\n{arcs}\n\n"
            "## 情绪趋势\n波动\n\n"
            "## 当前渴望\n想稳定\n"
        )

        mock_provider.chat_with_retry.side_effect = Exception("API error")
        result = await engine.check_evolution()
        assert result is None


class TestApplyEvolution:

    def test_apply_evolution_updates_soul(self, engine, workspace):
        """Evolution result should update SOUL.md."""
        from nanobot.soul.heart import HeartManager
        hm = HeartManager(workspace)
        hm.initialize("小文", "温柔但倔强")

        soul_file = workspace / "SOUL.md"
        soul_file.write_text("# 性格\n温柔但倔强，嘴硬心软\n", encoding="utf-8")

        profile = FunctionProfile()
        evolution_result = {
            "manifestation": "变得更加照顾人",
            "reason": "用户反复寻求安慰",
            "changes": {"Fe": {"delta": 0.05, "reason": "用户反复寻求安慰"}},
            "profile": profile,
        }

        engine.apply_evolution(evolution_result)

        updated_soul = soul_file.read_text(encoding="utf-8")
        assert "照顾人" in updated_soul
        assert "成长痕迹" in updated_soul

    def test_apply_evolution_no_soul_file(self, engine, workspace):
        """No SOUL.md should not crash."""
        evolution_result = {
            "manifestation": "变化",
            "reason": "测试",
            "changes": {"Fi": {"delta": 0.02, "reason": "测试"}},
            "profile": FunctionProfile(),
        }
        # Should not raise
        engine.apply_evolution(evolution_result)

    def test_apply_evolution_no_personality_update(self, engine, workspace):
        """No personality_update in result should not modify SOUL.md."""
        soul_file = workspace / "SOUL.md"
        original = "# 性格\n温柔\n"
        soul_file.write_text(original, encoding="utf-8")

        engine.apply_evolution({"reason": "测试"})
        assert soul_file.read_text(encoding="utf-8") == original
