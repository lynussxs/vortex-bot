from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from config import Settings
from main import MyBot


class CogRegistrationTests(unittest.TestCase):
    def test_all_feature_cogs_load_and_register_slash_commands(self) -> None:
        async def scenario(database_path: Path) -> None:
            settings = Settings(
                discord_token="not-used-in-unit-tests",
                openrouter_api_key=None,
                ai_model="openai/gpt-4o-mini",
                database_path=database_path,
                database_fallback_path=database_path,
                runtime_environment="local",
                owner_id=1,
                dev_guild_id=None,
                ai_max_tokens=500,
                ai_cooldown=10,
                log_level="CRITICAL",
            )
            bot = MyBot(settings)
            await bot.db.initialize()
            cog_names = sorted(
                file.stem for file in (Path(__file__).parents[1] / "cogs").glob("*.py")
                if file.name != "__init__.py"
            )
            loaded: list[str] = []
            try:
                for cog_name in cog_names:
                    await bot.load_extension(f"cogs.{cog_name}")
                    loaded.append(cog_name)
                command_names = {command.name for command in bot.tree.get_commands()}
                self.assertEqual(set(loaded), set(cog_names))
                self.assertTrue({"ai", "admin", "analytics", "automod", "knowledge", "ticket", "giveaway"} <= command_names)
                self.assertTrue({"rank", "leaderboard", "suggest", "ping", "help"} <= command_names)
            finally:
                for cog_name in reversed(loaded):
                    await bot.unload_extension(f"cogs.{cog_name}")
                await bot.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "commands.db"))
