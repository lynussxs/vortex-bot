from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.ai_assistant import AIAssistantCog


def make_cog(owner_only: bool = True):
    ai = SimpleNamespace(enabled=True, chat=AsyncMock(return_value="answer"))
    db = SimpleNamespace(fetchone=AsyncMock(return_value=None), fetchall=AsyncMock(return_value=[]), execute=AsyncMock(return_value=0))
    settings = SimpleNamespace(owner_id=111, ai_owner_only=owner_only, ai_cooldown=1, ai_model="m")
    bot = SimpleNamespace(user=SimpleNamespace(id=99, name="Vortex"), ai=ai, db=db, settings=settings)
    return AIAssistantCog(bot), bot


def make_message(author_id: int):
    return SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=author_id, bot=False),
        webhook_id=None,
        mentions=[SimpleNamespace(id=99)],
        content="<@99> check allserver",
        channel=SimpleNamespace(id=5),
        reply=AsyncMock(),
    )


class OwnerOnlyTests(unittest.TestCase):
    def test_member_gets_fixed_greeting_and_no_ai_call(self) -> None:
        cog, bot = make_cog()
        message = make_message(222)
        asyncio.run(cog.on_message(message))
        bot.ai.chat.assert_not_called()
        message.reply.assert_awaited_once()
        self.assertIn("/help", message.reply.await_args.args[0])

    def test_member_greeting_is_rate_limited(self) -> None:
        cog, _ = make_cog()
        message = make_message(222)
        asyncio.run(cog.on_message(message))
        asyncio.run(cog.on_message(message))
        self.assertEqual(message.reply.await_count, 1)


if __name__ == "__main__":
    unittest.main()
