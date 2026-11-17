"""Mention-only OpenRouter assistant and per-server AI configuration."""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from core.ai_client import AIServiceError
from core.ai_context import (
    build_messages,
    get_system_prompt,
    owner_bot_config,
    owner_server_context,
    public_server_context,
    retrieve_knowledge,
)
from core.cooldowns import Cooldowns
from core.embed_builder import error_embed, make_embed, success_embed
from utils.constants import AI_INPUT_LIMIT

logger = logging.getLogger("vortex.ai")
BOT_MENTION_RE = re.compile(r"<@!?(?P<id>\d+)>")


def extract_mention_prompt(content: str, bot_id: int) -> str | None:
    if not any(int(match.group("id")) == bot_id for match in BOT_MENTION_RE.finditer(content)):
        return None
    prompt = BOT_MENTION_RE.sub(
        lambda match: "" if int(match.group("id")) == bot_id else match.group(0),
        content,
    ).strip()
    return prompt[:AI_INPUT_LIMIT] or None


class AIAssistantCog(commands.Cog):
    ai_group = app_commands.Group(name="ai", description="Configure Vortex's AI assistant.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cooldowns = Cooldowns()

    async def _settings(self, guild_id: int) -> dict:
        await self.bot.db.execute("INSERT OR IGNORE INTO ai_settings(guild_id) VALUES (?)", (guild_id,))
        row = await self.bot.db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if (
            not message.guild
            or message.author.bot
            or message.webhook_id
            or not self.bot.user
            or self.bot.user.id not in {user.id for user in message.mentions}
        ):
            return

        prompt = extract_mention_prompt(message.content, self.bot.user.id)
        if not prompt:
            return
        settings = await self._settings(message.guild.id)
        if not settings.get("enabled"):
            await message.reply(
                "The AI assistant is disabled in this server. An administrator can enable it with `/ai enable`.",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        remaining = self._cooldowns.remaining(message.guild.id, message.author.id)
        if remaining > 0:
            await message.reply(
                f"Please wait {int(remaining + 0.99)} seconds before asking Vortex again.",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if not self.bot.ai.enabled:
            await message.reply(
                "AI replies are unavailable because the OpenRouter connection is not configured.",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        cooldown = max(1, int(self.bot.settings.ai_cooldown))
        self._cooldowns.start(message.guild.id, message.author.id, cooldown)
        try:
            history_rows = await self.bot.db.fetchall(
                """SELECT role, content FROM ai_conversations
                   WHERE guild_id = ? AND user_id = ? AND channel_id = ?
                   ORDER BY id DESC LIMIT 8""",
                (message.guild.id, message.author.id, message.channel.id),
            )
            history = [dict(row) for row in reversed(history_rows)]
            knowledge = await retrieve_knowledge(self.bot.db, message.guild.id, prompt)
            system_prompt = await get_system_prompt(self.bot.db, message.guild.id)
            # Owner status is decided here in code from OWNER_ID, never from message text.
            is_owner = self.bot.settings.owner_id is not None and message.author.id == self.bot.settings.owner_id
            if is_owner:
                server_context = (
                    owner_server_context(message.guild)
                    + "\n\n"
                    + await owner_bot_config(self.bot.db, message.guild.id)
                )
            else:
                server_context = public_server_context(message.guild)
            request_messages = build_messages(
                system_prompt,
                server_context,
                knowledge,
                history,
                prompt,
                owner_mode=is_owner,
            )
            async with message.channel.typing():
                answer = await self.bot.ai.chat(
                    request_messages,
                    model=settings.get("model") or self.bot.settings.ai_model,
                )
            await self.bot.db.execute(
                """INSERT INTO ai_conversations(guild_id, user_id, channel_id, role, content)
                   VALUES (?, ?, ?, 'user', ?)""",
                (message.guild.id, message.author.id, message.channel.id, prompt),
            )
            await self.bot.db.execute(
                """INSERT INTO ai_conversations(guild_id, user_id, channel_id, role, content)
                   VALUES (?, ?, ?, 'assistant', ?)""",
                (message.guild.id, message.author.id, message.channel.id, answer),
            )
            await self.bot.db.execute(
                """DELETE FROM ai_conversations WHERE guild_id = ? AND user_id = ? AND channel_id = ?
                   AND id NOT IN (SELECT id FROM ai_conversations
                                  WHERE guild_id = ? AND user_id = ? AND channel_id = ?
                                  ORDER BY id DESC LIMIT 10)""",
                (message.guild.id, message.author.id, message.channel.id,
                 message.guild.id, message.author.id, message.channel.id),
            )
            for start in range(0, len(answer), 1900):
                await message.reply(
                    answer[start:start + 1900],
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except AIServiceError as exc:
            await message.reply(str(exc), mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.exception("Could not deliver an AI response in guild %s", message.guild.id)
        except Exception:
            logger.exception("AI response failed in guild %s", message.guild.id)
            try:
                await message.reply(
                    "I could not answer that right now. Please try again later.",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass

    @ai_group.command(name="enable", description="Enable mention-only AI replies in this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def enable(self, interaction: discord.Interaction) -> None:
        if not self.bot.ai.enabled:
            await interaction.response.send_message(embed=error_embed("OpenRouter is not configured for this bot."), ephemeral=True)
            return
        await self.bot.db.execute(
            "INSERT INTO ai_settings(guild_id, enabled) VALUES (?, 1) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled = 1, updated_at = CURRENT_TIMESTAMP",
            (interaction.guild_id,),
        )
        await interaction.response.send_message(
            embed=success_embed("AI enabled", "Vortex will answer messages that directly mention it."),
            ephemeral=True,
        )

    @ai_group.command(name="disable", description="Disable AI replies in this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def disable(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute(
            "INSERT INTO ai_settings(guild_id, enabled) VALUES (?, 0) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled = 0, updated_at = CURRENT_TIMESTAMP",
            (interaction.guild_id,),
        )
        await interaction.response.send_message(embed=success_embed("AI disabled", "Vortex will not send AI responses in this server."), ephemeral=True)

    @ai_group.command(name="setprompt", description="Replace the server-specific AI instructions.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def set_prompt(self, interaction: discord.Interaction, prompt: app_commands.Range[str, 30, 4000]) -> None:
        await self.bot.db.execute(
            """INSERT INTO custom_ai_prompts(guild_id, prompt) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET prompt = excluded.prompt, updated_at = CURRENT_TIMESTAMP""",
            (interaction.guild_id, prompt.strip()),
        )
        await interaction.response.send_message(embed=success_embed("AI instructions updated", "The server prompt was saved."), ephemeral=True)

    @ai_group.command(name="showprompt", description="Preview this server's current AI instructions.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def show_prompt(self, interaction: discord.Interaction) -> None:
        prompt = await get_system_prompt(self.bot.db, interaction.guild_id)
        await interaction.response.send_message(
            embed=make_embed("Server AI instructions", prompt[:4000]),
            ephemeral=True,
        )

    @ai_group.command(name="resetprompt", description="Restore Vortex's default server instructions.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def reset_prompt(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute("DELETE FROM custom_ai_prompts WHERE guild_id = ?", (interaction.guild_id,))
        await interaction.response.send_message(embed=success_embed("Default instructions restored", "Vortex's secure default prompt is active again."), ephemeral=True)

    @ai_group.command(name="setmodel", description="Choose an OpenRouter model for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def set_model(self, interaction: discord.Interaction, model: app_commands.Range[str, 3, 128]) -> None:
        try:
            valid_model = self.bot.ai.validate_model(model)
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        await self.bot.db.execute(
            """INSERT INTO ai_settings(guild_id, model) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET model = excluded.model, updated_at = CURRENT_TIMESTAMP""",
            (interaction.guild_id, valid_model),
        )
        await interaction.response.send_message(embed=success_embed("AI model updated", f"Configured `{valid_model}`. Use `/ai test` to verify it."), ephemeral=True)

    @ai_group.command(name="status", description="Show AI availability and server settings.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        settings = await self._settings(interaction.guild_id)
        embed = make_embed("AI assistant status")
        embed.add_field(name="Server enabled", value="Yes" if settings.get("enabled") else "No")
        embed.add_field(name="OpenRouter configured", value="Yes" if self.bot.ai.enabled else "No")
        embed.add_field(name="Model", value=settings.get("model") or self.bot.settings.ai_model)
        embed.add_field(name="Response trigger", value="Direct Vortex mention only", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai_group.command(name="test", description="Send a short test request to the configured model.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def test(self, interaction: discord.Interaction) -> None:
        settings = await self._settings(interaction.guild_id)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            answer = await self.bot.ai.chat(
                [{"role": "system", "content": "Reply with a brief greeting in the user's language."},
                 {"role": "user", "content": "Vortex AI connection test."}],
                model=settings.get("model") or self.bot.settings.ai_model,
            )
        except AIServiceError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
            return
        await interaction.followup.send(embed=success_embed("AI connection works", answer[:1500]), ephemeral=True)

    @ai_group.command(name="clearhistory", description="Clear one member's saved AI conversation history.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def clear_history(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        target = member or interaction.user
        await self.bot.db.execute(
            "DELETE FROM ai_conversations WHERE guild_id = ? AND user_id = ?",
            (interaction.guild_id, target.id),
        )
        await interaction.response.send_message(
            embed=success_embed("AI history cleared", f"Removed saved conversation context for {target.mention}."),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIAssistantCog(bot))
