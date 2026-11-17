"""Vortex entry point: configure, load cogs, and synchronize slash commands."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from config import Settings
from core.ai_client import OpenRouterClient
from core.database import Database
from core.embed_builder import set_branding
from core.error_handler import handle_app_command_error


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class Vortex(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        intents.moderation = True
        intents.voice_states = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
            help_command=None,
        )
        self.settings = settings
        self.db = Database(
            settings.database_path,
            fallback_path=(
                settings.database_fallback_path
                if settings.runtime_environment == "replit"
                else None
            ),
            runtime_environment=settings.runtime_environment,
        )
        self.ai = OpenRouterClient(
            settings.openrouter_api_key,
            settings.ai_model,
            settings.ai_max_tokens,
        )
        self.logger = logging.getLogger("vortex")
        self.tree.on_error = handle_app_command_error
        self._shutdown_started = False

    async def setup_hook(self) -> None:
        await self.db.initialize()
        await self.ai.start()

        cogs_path = Path(__file__).parent / "cogs"
        cog_names = sorted(
            file.stem for file in cogs_path.glob("*.py")
            if file.name != "__init__.py" and not file.name.startswith("_")
        )
        for cog_name in cog_names:
            await self.load_extension(f"cogs.{cog_name}")
            self.logger.info("Loaded cog %s", cog_name)

        if self.settings.dev_guild_id:
            guild = discord.Object(id=self.settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            self.logger.info("Synchronized %d slash commands to development guild", len(synced))
            await self._wipe_global_commands()
        else:
            synced = await self.tree.sync()
            self.logger.info("Synchronized %d global slash commands", len(synced))

    async def _wipe_global_commands(self) -> None:
        """Remove stale global commands from Discord so they don't duplicate the dev-guild ones."""
        global_commands = self.tree.get_commands()
        self.tree.clear_commands(guild=None)
        try:
            await self.tree.sync()
            self.logger.info("Cleared stale global slash commands (development mode).")
        finally:
            for command in global_commands:  # keep them in memory for reloads and status counts
                self.tree.add_command(command)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        # The prefix is "@bot", so every mention is parsed as a command attempt.
        # Plain chat with the bot is handled by the AI cog, so ignore "not found".
        if isinstance(error, commands.CommandNotFound):
            return
        self.logger.error("Prefix command error: %s", error, exc_info=error)

    async def on_ready(self) -> None:
        if self.user is None:
            return
        set_branding(self.user.name, self.user.display_avatar.url)
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(type=discord.ActivityType.watching, name="/help • quản lý server"),
        )

        def count_commands(command: app_commands.Command | app_commands.Group) -> int:
            children = command.commands if isinstance(command, app_commands.Group) else []
            return 1 + sum(count_commands(child) for child in children)

        command_count = sum(count_commands(command) for command in self.tree.get_commands())
        self.logger.info(
            "Connected as %s (ID %s) | guilds=%d | cogs=%d | commands=%d | database=%s | AI=%s",
            self.user.name,
            self.user.id,
            len(self.guilds),
            len(self.extensions),
            command_count,
            "ready" if self.db.connected else "unavailable",
            "configured" if self.ai.enabled else "not configured",
        )

    async def close(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self.logger.info("Shutting down Vortex.")
        try:
            for extension in list(self.extensions):
                try:
                    await self.unload_extension(extension)
                except Exception:
                    self.logger.exception("Could not cleanly unload extension %s", extension)
            await super().close()
        finally:
            await self.ai.close()
            await self.db.close()


async def run() -> None:
    load_dotenv()
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    bot = Vortex(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.close()))
        except NotImplementedError:
            pass
    try:
        await bot.start(settings.discord_token)
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(run())
