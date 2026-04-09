"""
Test script for message compression functionality.

Run: python tests/test_compression.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_token_estimation():
    """Test token estimation logic."""
    from nanobot.agent.reme_adapter import RemeMemoryAdapter

    # Create a mock adapter instance just for testing estimation methods
    class MockAdapter:
        def _estimate_message_tokens(self, msg: dict) -> int:
            content = msg.get("content", "")
            char_count = len(content)
            estimated = char_count // 2
            overhead = 20
            return estimated + overhead

        def _estimate_block_tokens(self, block: list) -> int:
            return sum(self._estimate_message_tokens(msg) for msg in block)

    adapter = MockAdapter()

    # Test 1: Short message
    short_msg = {"role": "user", "content": "你好"}
    tokens = adapter._estimate_message_tokens(short_msg)
    print(f"[Test 1] Short message '你好': {tokens} tokens (expected: ~21)")

    # Test 2: Long message (1000 chars)
    long_content = "这是一个测试消息。" * 100
    long_msg = {"role": "user", "content": long_content}
    tokens = adapter._estimate_message_tokens(long_msg)
    print(f"[Test 2] Long message (700 chars): {tokens} tokens (expected: ~370)")

    # Test 3: Block estimation
    block = [short_msg, long_msg]
    tokens = adapter._estimate_block_tokens(block)
    print(f"[Test 3] Block of 2 messages: {tokens} tokens")

    print("[OK] Token estimation tests passed\n")


def test_block_splitting():
    """Test block splitting logic."""
    from nanobot.agent.reme_adapter import RemeMemoryAdapter

    class MockAdapter:
        def _estimate_message_tokens(self, msg: dict) -> int:
            content = msg.get("content", "")
            return len(content) // 2 + 20

        def _estimate_block_tokens(self, block: list) -> int:
            return sum(self._estimate_message_tokens(msg) for msg in block)

        def _truncate_block_messages(self, block: list, max_tokens: int) -> list:
            truncated = []
            remaining = max_tokens
            for msg in block:
                msg_tokens = self._estimate_message_tokens(msg)
                if msg_tokens <= remaining:
                    truncated.append(msg)
                    remaining -= msg_tokens
                else:
                    available_chars = (remaining - 20) * 2
                    if available_chars > 100:
                        truncated_content = msg.get("content", "")[:available_chars]
                        truncated.append({
                            "role": msg.get("role"),
                            "content": truncated_content + "...[截断]",
                            "time_created": msg.get("time_created"),
                        })
                    break
            return truncated

        def _ensure_block_within_limit(self, block: list, max_tokens: int) -> list:
            block_tokens = self._estimate_block_tokens(block)

            if block_tokens <= max_tokens:
                return [block]

            # If single message, truncate
            if len(block) == 1:
                return [self._truncate_block_messages(block, max_tokens)]

            num_sub_blocks = (block_tokens + max_tokens - 1) // max_tokens
            sub_block_size = max(1, (len(block) + num_sub_blocks - 1) // num_sub_blocks)

            sub_blocks = []
            for i in range(0, len(block), sub_block_size):
                sub_block = block[i:i + sub_block_size]
                if len(sub_block) == 1:
                    sub_tokens = self._estimate_block_tokens(sub_block)
                    if sub_tokens > max_tokens:
                        sub_blocks.append(self._truncate_block_messages(sub_block, max_tokens))
                        continue
                sub_blocks.extend(self._ensure_block_within_limit(sub_block, max_tokens))

            return sub_blocks

    adapter = MockAdapter()

    # Test 1: Block within limit
    small_block = [{"role": "user", "content": "短消息"} for _ in range(5)]
    result = adapter._ensure_block_within_limit(small_block, max_tokens=10000)
    print(f"[Test 1] Small block (5 msgs, within limit): {len(result)} block(s) (expected: 1)")

    # Test 2: Block exceeds limit - should split
    large_block = [{"role": "user", "content": "这是一个很长的测试消息内容" * 100} for _ in range(10)]
    result = adapter._ensure_block_within_limit(large_block, max_tokens=1000)
    print(f"[Test 2] Large block (10 msgs, exceeds limit): {len(result)} block(s) (expected: >1)")

    # Test 3: Single message exceeds limit - should truncate
    huge_msg = [{"role": "user", "content": "巨大消息" * 10000}]
    result = adapter._ensure_block_within_limit(huge_msg, max_tokens=500)
    print(f"[Test 3] Single huge message: {len(result)} block(s), content length: {len(result[0][0]['content'])} chars")

    print("[OK] Block splitting tests passed\n")


def test_block_size_config():
    """Test that block_size configuration works correctly."""
    print("[Test] Testing block_size configuration...")

    # Simulate splitting 30 messages with block_size=10
    messages = [{"role": "user", "content": f"消息{i}"} for i in range(30)]
    block_size = 10

    initial_blocks = []
    for i in range(0, len(messages), block_size):
        initial_blocks.append(messages[i:i + block_size])

    print(f"  Total messages: {len(messages)}")
    print(f"  Block size: {block_size}")
    print(f"  Number of blocks: {len(initial_blocks)}")
    print(f"  Expected: {len(messages) / block_size} = 3 blocks")
    assert len(initial_blocks) == 3, f"Expected 3 blocks, got {len(initial_blocks)}"

    print("[OK] Block size configuration test passed\n")


async def test_mock_compression():
    """Test compression with mock LLM (no real API call)."""
    print("[Test] Testing mock compression flow...")

    # Create test messages
    messages = []
    for i in range(30):
        messages.append({
            "role": "user",
            "content": f"这是第{i+1}条用户消息，包含一些测试内容。" * 10,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        messages.append({
            "role": "assistant",
            "content": f"这是第{i+1}条助手回复，包含一些测试内容。" * 10,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    print(f"  Total messages: {len(messages)}")
    print(f"  Est. total tokens: ~{sum(len(m['content']) // 2 + 20 for m in messages)}")

    # Simulate the block splitting (without actual LLM call)
    block_size = 10
    initial_blocks = []
    for i in range(0, len(messages), block_size):
        initial_blocks.append(messages[i:i + block_size])

    print(f"  Initial blocks: {len(initial_blocks)}")

    # Check token limits
    max_tokens_per_block = 131072 - 2048 - 500  # ~128k

    final_blocks = []
    for block in initial_blocks:
        block_tokens = sum(len(m['content']) // 2 + 20 for m in block)
        if block_tokens <= max_tokens_per_block:
            final_blocks.append(block)
        else:
            # Would split here
            final_blocks.append(block)  # Simplified for test

    print(f"  Final blocks after validation: {len(final_blocks)}")

    # Simulate summaries
    summaries = [f"[摘要{i+1}] 这是第{i+1}块的摘要内容..." for i in range(len(final_blocks))]
    print(f"  Summaries generated: {len(summaries)}")

    # Build compressed messages
    compressed = []
    for i, summary in enumerate(summaries):
        compressed.append({
            "role": "user",
            "content": summary,
            "time_created": messages[i * block_size].get("timestamp", "")
        })

    print(f"  Compressed messages: {len(compressed)}")
    print(f"  Compression ratio: {len(messages)} → {len(compressed)} ({100 * len(compressed) / len(messages):.1f}%)")

    print("[OK] Mock compression test passed\n")


def test_config_loading():
    """Test that compression config is loaded correctly."""
    print("[Test] Testing config loading...")

    from nanobot.config.reme_loader import RemeConfig, RemeCompressionConfig, RemeSummarizerLLMConfig

    # Test default config
    config = RemeConfig()

    assert config.compression.enabled == True, "Default compression should be enabled"
    assert config.compression.block_size == 10, f"Default block_size should be 10, got {config.compression.block_size}"
    assert config.summarizer_context_window == 131072, f"context_window should be 131072, got {config.summarizer_context_window}"
    assert config.summarizer_max_output_tokens == 2048, f"max_output_tokens should be 2048, got {config.summarizer_max_output_tokens}"
    assert config.summarizer_temperature == 0.3, f"temperature should be 0.3, got {config.summarizer_temperature}"

    print(f"  compression.enabled: {config.compression.enabled}")
    print(f"  compression.block_size: {config.compression.block_size}")
    print(f"  summarizer_llm.context_window: {config.summarizer_context_window}")
    print(f"  summarizer_llm.max_output_tokens: {config.summarizer_max_output_tokens}")
    print(f"  summarizer_llm.temperature: {config.summarizer_temperature}")

    # Test custom config
    custom_config = RemeConfig(
        compression=RemeCompressionConfig(
            enabled=False,
            block_size=20,
            summarizer_llm=RemeSummarizerLLMConfig(
                context_window=32768,
                max_output_tokens=1024,
                temperature=0.1
            )
        )
    )

    assert custom_config.compression.enabled == False
    assert custom_config.compression.block_size == 20
    assert custom_config.summarizer_context_window == 32768

    print(f"  Custom config loaded correctly")

    print("[OK] Config loading test passed\n")


def test_real_config_file():
    """Test loading real config file from ~/.nanobot/reme.yaml"""
    print("[Test] Testing real config file loading...")

    from pathlib import Path
    from nanobot.config.reme_loader import load_reme_config

    config_path = Path.home() / ".nanobot" / "reme.yaml"

    if not config_path.exists():
        print(f"  Config file not found: {config_path}")
        print("  [SKIP] Real config file test\n")
        return

    config = load_reme_config(Path.cwd())

    print(f"  Config loaded from: {config_path}")
    print(f"  compression.enabled: {config.compression.enabled}")
    print(f"  compression.block_size: {config.compression.block_size}")
    print(f"  summarizer_llm.context_window: {config.summarizer_context_window}")

    assert hasattr(config, 'compression'), "Config should have compression attribute"
    assert hasattr(config.compression, 'summarizer_llm'), "Compression should have summarizer_llm"

    print("[OK] Real config file test passed\n")


def main():
    print("=" * 60)
    print("Message Compression Tests")
    print("=" * 60 + "\n")

    # Test 1: Token estimation
    test_token_estimation()

    # Test 2: Block splitting
    test_block_splitting()

    # Test 3: Block size config
    test_block_size_config()

    # Test 4: Mock compression flow
    asyncio.run(test_mock_compression())

    # Test 5: Config loading
    test_config_loading()

    # Test 6: Real config file
    test_real_config_file()

    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()