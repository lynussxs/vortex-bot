"""Moderation commands with role hierarchy checks and a persistent audit trail."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, make_embed, success_embed
from core.permissions import can_moderate
from utils.helpers import decode_json_list
from utils.validators import parse_duration

logger = logging.getLogger("vortex.moderation")


class ModerationCog(commands.Cog):
    warn = app_commands.Group(name="warn", description="Add or remove a member warning.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _log_action(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target_id: int,
        action: str,
        reason: str,
        duration: int | None = None,
    ) -> None:
        await self.bot.db.execute(
            """INSERT INTO moderation_logs
               (guild_id, moderator_id, target_id, action, reason, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild.id, moderator.id, target_id, action, reason[:1000], duration),
        )
        row = await self.bot.db.fetchone(
            "SELECT channel_id, events FROM logging_settings WHERE guild_id = ?",
            (guild.id,),
        )
        channel_id = row["channel_id"] if row and "moderation" in decode_json_list(row["events"]) else None
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            embed = make_embed(f"Moderation: {action.title()}", reason)
            embed.add_field(name="Member", value=f"<@{target_id}> (`{target_id}`)", inline=False)
            embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)
            if duration is not None:
                embed.add_field(name="Duration", value=f"{duration} seconds")
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                logger.warning("Could not send moderation log in guild %s", guild.id)

    async def _get_target(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
    ) -> tuple[discord.Guild, discord.Member] | None:
        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member):
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return None
        allowed, reason = can_moderate(moderator, target, guild.me)
        if not allowed:
            await interaction.response.send_message(embed=error_embed(reason), ephemeral=True)
            return None
        return guild, moderator

    async def _do_moderation(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        action: str,
        reason: str,
        duration_seconds: int | None = None,
    ) -> tuple[discord.Guild, discord.Member] | None:
        context = await self._get_target(interaction, target)
        if context is None:
            return None
        guild, moderator = context
        try:
            if action == "ban":
                await target.ban(reason=reason[:500], delete_message_seconds=0)
            elif action == "kick":
                await target.kick(reason=reason[:500])
            elif action == "timeout":
                assert duration_seconds is not None
                await target.timeout(timedelta(seconds=duration_seconds), reason=reason[:500])
            elif action == "untimeout":
                await target.timeout(None, reason=reason[:500])
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Vortex lacks the required permission or role position."),
                ephemeral=True,
            )
            return None
        except discord.HTTPException as exc:
            logger.warning("%s failed in guild %s: %s", action, guild.id, exc)
            await interaction.response.send_message(embed=error_embed("Discord could not complete that action."), ephemeral=True)
            return None
        await self._log_action(guild, moderator, target.id, action, reason, duration_seconds)
        await interaction.response.send_message(
            embed=success_embed(f"{action.title()} complete", f"{target.mention}: {reason}"),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return guild, moderator

    @app_commands.command(name="ban", description="Ban a member from this server.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ) -> None:
        await self._do_moderation(interaction, member, "ban", reason)

    @app_commands.command(name="kick", description="Remove a member from this server.")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ) -> None:
        await self._do_moderation(interaction, member, "kick", reason)

    @app_commands.command(name="timeout", description="Temporarily prevent a member from chatting.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str = "No reason provided",
    ) -> None:
        try:
            seconds = parse_duration(duration)
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        await self._do_moderation(interaction, member, "timeout", reason, seconds)

    @app_commands.command(name="untimeout", description="Remove a member's timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def untimeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ) -> None:
        await self._do_moderation(interaction, member, "untimeout", reason)

    @warn.command(name="add", description="Issue a warning to a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ) -> None:
        context = await self._get_target(interaction, member)
        if context is None:
            return
        guild, moderator = context
        await self.bot.db.execute(
            "INSERT INTO warnings(guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
            (guild.id, member.id, moderator.id, reason[:1000]),
        )
        await self._log_action(guild, moderator, member.id, "warn", reason)
        await interaction.response.send_message(
            embed=success_embed("Warning recorded", f"{member.mention}: {reason}"),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @warn.command(name="remove", description="Remove a warning by its ID.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_remove(self, interaction: discord.Interaction, warning_id: int) -> None:
        guild = interaction.guild
        if guild is None:
            return
        row = await self.bot.db.fetchone(
            "SELECT user_id FROM warnings WHERE id = ? AND guild_id = ? AND active = 1",
            (warning_id, guild.id),
        )
        if row is None:
            await interaction.response.send_message(embed=error_embed("No active warning has that ID."), ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE warnings SET active = 0 WHERE id = ? AND guild_id = ?",
            (warning_id, guild.id),
        )
        await interaction.response.send_message(
            embed=success_embed("Warning removed", f"Warning `{warning_id}` was removed."),
            ephemeral=True,
        )

    @app_commands.command(name="warnings", description="List a member's active warnings.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        guild = interaction.guild
        if guild is None:
            return
        rows = await self.bot.db.fetchall(
            """SELECT id, moderator_id, reason, created_at FROM warnings
               WHERE guild_id = ? AND user_id = ? AND active = 1 ORDER BY id DESC LIMIT 20""",
            (guild.id, member.id),
        )
        embed = make_embed(f"Warnings for {member}", f"{len(rows)} active warning(s).")
        for row in rows[:10]:
            embed.add_field(
                name=f"#{row['id']} · {row['created_at']}",
                value=f"{str(row['reason'])[:500]}\nModerator: <@{row['moderator_id']}>",
                inline=False,
            )
        if not rows:
            embed.description = "No active warnings."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clear", description="Delete recent messages from this channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command requires a text channel.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount, reason=f"Cleared by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(embed=error_embed("Vortex cannot manage messages in this channel."), ephemeral=True)
            return
        await interaction.followup.send(
            embed=success_embed("Messages cleared", f"Deleted **{len(deleted)}** message(s)."),
            ephemeral=True,
        )

    @app_commands.command(name="lock", description="Prevent members from sending messages in this channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def lock(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command requires a text channel.", ephemeral=True)
            return
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            send_messages=False,
            reason=f"Locked by {interaction.user}",
        )
        await interaction.response.send_message(
            embed=success_embed("Channel locked", "Members can no longer send messages here."),
        )

    @app_commands.command(name="unlock", description="Allow members to send messages in this channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def unlock(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command requires a text channel.", ephemeral=True)
            return
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            send_messages=None,
            reason=f"Unlocked by {interaction.user}",
        )
        await interaction.response.send_message(
            embed=success_embed("Channel unlocked", "The default message permission has been restored."),
        )

    @app_commands.command(name="slowmode", description="Set this channel's slowmode interval.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600],
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command requires a text channel.", ephemeral=True)
            return
        await interaction.channel.edit(slowmode_delay=seconds, reason=f"Set by {interaction.user}")
        await interaction.response.send_message(
            embed=success_embed("Slowmode updated", f"Interval: **{seconds} seconds**."),
            ephemeral=True,
        )

    @app_commands.command(name="modlogs", description="Review recent moderation actions for a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def modlogs(self, interaction: discord.Interaction, member: discord.Member) -> None:
        guild = interaction.guild
        if guild is None:
            return
        rows = await self.bot.db.fetchall(
            """SELECT action, moderator_id, reason, created_at FROM moderation_logs
               WHERE guild_id = ? AND target_id = ? ORDER BY id DESC LIMIT 10""",
            (guild.id, member.id),
        )
        embed = make_embed(f"Moderation history for {member}", f"{len(rows)} recent action(s).")
        for row in rows:
            embed.add_field(
                name=f"{row['action'].title()} · {row['created_at']}",
                value=f"{str(row['reason'])[:500]}\nModerator: <@{row['moderator_id']}>",
                inline=False,
            )
        if not rows:
            embed.description = "No moderation history was found."
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
