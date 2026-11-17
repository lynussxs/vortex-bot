"""Configurable event logs for server moderation and community changes."""

from __future__ import annotations

from datetime import timedelta
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, make_embed, success_embed
from utils.helpers import decode_json_list, encode_json_list

LOG_EVENTS = (
    "member",
    "message",
    "role",
    "nickname",
    "channel",
    "voice",
    "moderation",
)
logger = logging.getLogger("mybot.logging")


class LoggingCog(commands.Cog):
    logs = app_commands.Group(name="logs", description="Configure server event logging.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _channel(self, guild: discord.Guild, event: str) -> discord.TextChannel | None:
        row = await self.bot.db.fetchone(
            "SELECT channel_id, events FROM logging_settings WHERE guild_id = ?",
            (guild.id,),
        )
        if not row or event not in decode_json_list(row["events"]):
            return None
        channel = guild.get_channel(row["channel_id"])
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _send(self, guild: discord.Guild, event: str, embed: discord.Embed) -> None:
        channel = await self._channel(guild, event)
        if channel:
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    async def _audit_actor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
    ) -> discord.User | discord.Member | None:
        me = guild.me
        if not me or not me.guild_permissions.view_audit_log:
            return None
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                target = entry.target
                age = discord.utils.utcnow() - entry.created_at
                if getattr(target, "id", None) == target_id and age <= timedelta(seconds=30):
                    return entry.user
        except discord.Forbidden:
            logger.info("Audit-log access is not available in guild %s", guild.id)
        except discord.HTTPException:
            logger.warning("Could not read audit logs in guild %s", guild.id)
        return None

    @logs.command(name="setup", description="Set the channel for server event logs.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup_logs(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        events = encode_json_list(list(LOG_EVENTS))
        await self.bot.db.execute(
            """INSERT INTO logging_settings(guild_id, channel_id, events) VALUES (?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id, events = excluded.events""",
            (interaction.guild_id, channel.id, events),
        )
        await self.bot.db.execute(
            """INSERT INTO guild_settings(guild_id, moderation_log_channel_id) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET moderation_log_channel_id = excluded.moderation_log_channel_id""",
            (interaction.guild_id, channel.id),
        )
        await interaction.response.send_message(embed=success_embed("Logs enabled", f"Event logs will be sent to {channel.mention}."), ephemeral=True)

    @logs.command(name="disable", description="Disable server event logs.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def disable_logs(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute("DELETE FROM logging_settings WHERE guild_id = ?", (interaction.guild_id,))
        await self.bot.db.execute(
            "UPDATE guild_settings SET moderation_log_channel_id = NULL WHERE guild_id = ?",
            (interaction.guild_id,),
        )
        await interaction.response.send_message(embed=success_embed("Logs disabled", "Event logging has been turned off."), ephemeral=True)

    @logs.command(name="config", description="Show or enable/disable an event category.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(event="Leave blank to view all event categories.")
    async def config(
        self,
        interaction: discord.Interaction,
        event: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        row = await self.bot.db.fetchone(
            "SELECT channel_id, events FROM logging_settings WHERE guild_id = ?",
            (interaction.guild_id,),
        )
        if row is None:
            await interaction.response.send_message(embed=error_embed("Run /logs setup first."), ephemeral=True)
            return
        events = decode_json_list(row["events"])
        if event and enabled is not None:
            if event not in LOG_EVENTS:
                await interaction.response.send_message(embed=error_embed("Unknown event category."), ephemeral=True)
                return
            if enabled and event not in events:
                events.append(event)
            elif not enabled and event in events:
                events.remove(event)
            await self.bot.db.execute(
                "UPDATE logging_settings SET events = ? WHERE guild_id = ?",
                (encode_json_list(events), interaction.guild_id),
            )
        channel = interaction.guild.get_channel(row["channel_id"])
        embed = make_embed("Logging configuration")
        embed.add_field(name="Channel", value=channel.mention if channel else "Unavailable")
        embed.add_field(name="Enabled categories", value=", ".join(events) or "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config.autocomplete("event")
    async def event_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=event.title(), value=event)
            for event in LOG_EVENTS if current.casefold() in event.casefold()
        ][:25]

    @logs.command(name="test", description="Send a test event to the configured log channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def test(self, interaction: discord.Interaction) -> None:
        row = await self.bot.db.fetchone(
            "SELECT channel_id FROM logging_settings WHERE guild_id = ?",
            (interaction.guild_id,),
        )
        channel = interaction.guild.get_channel(row["channel_id"]) if row else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Run /logs setup first."), ephemeral=True)
            return
        await channel.send(embed=make_embed("Logging test", f"Test requested by {interaction.user}."))
        await interaction.response.send_message(embed=success_embed("Test sent", f"Check {channel.mention}."), ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        embed = make_embed("Member joined", f"{member.mention} (`{member.id}`)")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"))
        await self._send(member.guild, "member", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        actor = await self._audit_actor(member.guild, discord.AuditLogAction.kick, member.id)
        if actor:
            embed = make_embed("Member kicked", f"{member} (`{member.id}`)\nModerator: {actor.mention}")
            await self._send(member.guild, "moderation", embed)
        else:
            await self._send(member.guild, "member", make_embed("Member left", f"{member} (`{member.id}`)"))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        actor = await self._audit_actor(guild, discord.AuditLogAction.ban, user.id)
        embed = make_embed("Member banned", f"{user} (`{user.id}`)")
        if actor:
            embed.add_field(name="Moderator", value=actor.mention)
        await self._send(guild, "moderation", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        actor = await self._audit_actor(guild, discord.AuditLogAction.unban, user.id)
        embed = make_embed("Member unbanned", f"{user} (`{user.id}`)")
        if actor:
            embed.add_field(name="Moderator", value=actor.mention)
        await self._send(guild, "moderation", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not before.guild or before.author.bot or before.content == after.content:
            return
        embed = make_embed(
            "Message edited",
            f"Author: {before.author.mention}\nChannel: {before.channel.mention}\nContent changed; text is not retained.",
        )
        embed.set_footer(text=f"Message ID: {before.id}")
        await self._send(before.guild, "message", embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        embed = make_embed(
            "Message deleted",
            f"Author: {message.author.mention}\nChannel: {message.channel.mention}\nDeleted text is not retained.",
        )
        embed.set_footer(text=f"Message ID: {message.id}")
        await self._send(message.guild, "message", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.nick != after.nick:
            await self._send(
                after.guild,
                "nickname",
                make_embed("Nickname changed", f"Member: {after.mention}\n`{before.nick or before.name}` → `{after.nick or after.name}`"),
            )
        before_roles = {role.id: role for role in before.roles}
        after_roles = {role.id: role for role in after.roles}
        added = [role.mention for key, role in after_roles.items() if key not in before_roles and not role.is_default()]
        removed = [role.mention for key, role in before_roles.items() if key not in after_roles and not role.is_default()]
        if added or removed:
            embed = make_embed("Member roles changed", after.mention)
            if added:
                embed.add_field(name="Added", value=", ".join(added[:20]), inline=False)
            if removed:
                embed.add_field(name="Removed", value=", ".join(removed[:20]), inline=False)
            await self._send(after.guild, "role", embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        await self._send(role.guild, "role", make_embed("Role created", f"{role.mention} (`{role.id}`)"))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self._send(role.guild, "role", make_embed("Role deleted", f"`{role.name}` (`{role.id}`)"))

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        if before.name != after.name or before.permissions != after.permissions or before.color != after.color:
            await self._send(after.guild, "role", make_embed("Role updated", f"`{before.name}` → `{after.name}` (`{after.id}`)"))

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self._send(channel.guild, "channel", make_embed("Channel created", f"{channel.mention} (`{channel.id}`)"))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self._send(channel.guild, "channel", make_embed("Channel deleted", f"`{channel.name}` (`{channel.id}`)"))

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        if before.name != after.name:
            await self._send(after.guild, "channel", make_embed("Channel renamed", f"`{before.name}` → `{after.name}`"))

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel == after.channel:
            return
        if before.channel is None:
            detail = f"{member.mention} joined {after.channel.mention if after.channel else 'a voice channel'}."
        elif after.channel is None:
            detail = f"{member.mention} left {before.channel.mention}."
        else:
            detail = f"{member.mention} moved from {before.channel.mention} to {after.channel.mention}."
        await self._send(member.guild, "voice", make_embed("Voice state changed", detail))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingCog(bot))
