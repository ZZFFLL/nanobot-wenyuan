from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_loop():
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop


@pytest.mark.asyncio
async def test_dispatch_publishes_before_post_send_finalizer():
    from nanobot.agent.loop import _ProcessMessageOutcome
    from nanobot.bus.events import InboundMessage, OutboundMessage

    loop = _make_loop()
    events: list[str] = []
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")

    async def post_send_finalizer() -> None:
        events.append("finalizer")

    async def fake_publish(outbound: OutboundMessage) -> None:
        events.append(f"publish:{outbound.content}")

    loop.bus.publish_outbound = AsyncMock(side_effect=fake_publish)
    loop._process_message_with_post_send = AsyncMock(return_value=_ProcessMessageOutcome(
        response=OutboundMessage(channel="test", chat_id="c1", content="hi"),
        post_send_finalizer=post_send_finalizer,
    ))

    await loop._dispatch(msg)

    assert events == ["publish:hi", "finalizer"]


@pytest.mark.asyncio
async def test_process_message_direct_caller_awaits_post_send_finalizer():
    from nanobot.agent.loop import _ProcessMessageOutcome
    from nanobot.bus.events import InboundMessage, OutboundMessage

    loop = _make_loop()
    events: list[str] = []
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")

    async def post_send_finalizer() -> None:
        events.append("finalizer")

    loop._process_message_with_post_send = AsyncMock(return_value=_ProcessMessageOutcome(
        response=OutboundMessage(channel="test", chat_id="c1", content="hi"),
        post_send_finalizer=post_send_finalizer,
    ))

    response = await loop._process_message(msg)

    assert response is not None
    assert response.content == "hi"
    assert events == ["finalizer"]


@pytest.mark.asyncio
async def test_dispatch_does_not_send_second_error_when_post_send_finalizer_fails():
    from nanobot.agent.loop import _ProcessMessageOutcome
    from nanobot.bus.events import InboundMessage, OutboundMessage

    loop = _make_loop()
    events: list[str] = []
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")

    async def post_send_finalizer() -> None:
        raise RuntimeError("post-send failed")

    async def fake_publish(outbound: OutboundMessage) -> None:
        events.append(outbound.content)

    loop.bus.publish_outbound = AsyncMock(side_effect=fake_publish)
    loop._process_message_with_post_send = AsyncMock(return_value=_ProcessMessageOutcome(
        response=OutboundMessage(channel="test", chat_id="c1", content="hi"),
        post_send_finalizer=post_send_finalizer,
    ))

    await loop._dispatch(msg)

    assert events == ["hi"]


@pytest.mark.asyncio
async def test_build_post_send_finalizer_forwards_all_msgs_and_final_content():
    loop = _make_loop()
    all_msgs = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        {"role": "assistant", "content": "hi"},
    ]
    loop._soul_engine = MagicMock()
    loop._soul_engine.finalize_post_send_turn = AsyncMock()

    finalizer = loop._build_post_send_finalizer(all_msgs, "final reply")

    assert finalizer is not None
    await finalizer()

    loop._soul_engine.finalize_post_send_turn.assert_awaited_once_with(
        messages=all_msgs,
        final_content="final reply",
    )
