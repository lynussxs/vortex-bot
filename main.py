"""Arcadia Bot - bot quan ly server Discord (lenh slash + AI)."""
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands

from core.db import Database, default_db_path

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("arcadia")

EXTENSIONS = (
    "cogs.setup", "cogs.moderation", "cogs.levels", "cogs.welcome",
    "cogs.logs", "cogs.automod", "cogs.utility", "cogs.ai",
)


class ArcadiaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True          # can bat "Server Members Intent" trong Developer Portal
        intents.message_content = True  # can bat "Message Content Intent"
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
            activity=discord.Activity(type=discord.ActivityType.watching,
                                      name=os.getenv("BOT_STATUS", "Arcadia.vn • /help")),
        )
        self.db = Database(default_db_path())
        self.tree.on_error = self.on_tree_error

    async def process_commands(self, message):  # chi dung lenh slash, khong dung lenh tien to
        return

    async def setup_hook(self):
        await self.db.connect()
        log.info("Database: %s", self.db.path)
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        guild_id = os.getenv("GUILD_ID")
        if guild_id:  # dong bo lenh tuc thi cho 1 server
            guild = discord.Object(int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:  # dong bo toan cau (co the mat toi 1 gio de hien)
            synced = await self.tree.sync()
        log.info("Đã đồng bộ %d lệnh slash", len(synced))

    async def on_ready(self):
        log.info("Bot sẵn sàng: %s (%s server)", self.user, len(self.guilds))

    async def close(self):
        await self.db.close()
        await super().close()

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ Bạn không có quyền dùng lệnh này."
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = "❌ Bot thiếu quyền: " + ", ".join(error.missing_permissions)
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ Chờ {error.retry_after:.0f}s rồi thử lại nhé."
        elif isinstance(error, app_commands.CheckFailure):
            msg = "❌ Bạn không thể dùng lệnh này ở đây."
        else:
            log.exception("Lỗi lệnh /%s", interaction.command.qualified_name if interaction.command else "?",
                          exc_info=error)
            msg = "⚠️ Có lỗi xảy ra, thử lại sau nhé."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        sys.exit("Thiếu DISCORD_TOKEN (đặt trong Railway Variables hoặc file .env).")
    try:
        ArcadiaBot().run(token, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        sys.exit("Chưa bật Intents: Developer Portal -> Bot -> bật 'Server Members Intent' và 'Message Content Intent'.")


if __name__ == "__main__":
    main()
