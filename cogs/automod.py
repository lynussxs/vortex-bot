"""Event-driven spam, flood, mention, link, word, and join-raid protection."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core.cooldowns import EventWindow
from core.embed_builder import make_embed, success_embed
from utils.helpers import decode_json_list, encode_json_list

logger = logging.getLogger("mybot.automod")
SUSPICIOUS_IP_URL = re.compile(r"https?://(?:\d{1,3}\.){3}\d{1,3}", re.IGNORECASE)
DISCORD_INVITE = re.compile(r"(?:discord\.gg/|discord(?:app)?\.com/invite/)[A-Za-z0-9-]+", re.IGNORECASE)


class AutomodCog(commands.Cog):
    automod = app_commands.Group(name="automod", description="Configure automatic server protections.")
    whitelist = app_commands.Group(name="whitelist", description="Manage automod exemptions.", parent=automod)
    blacklist = app_commands.Group(name="blacklist", description="Manage blocked channels and words.", parent=automod)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._message_events: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)
        self._join_events = EventWindow()
        self._violations: dict[tuple[int, int], int] = defaultdict(int)
        self._action_cooldown: dict[tuple[int, int], float] = {}
        self._settings_cache: dict[int, tuple[float, dict]] = {}

    def _invalidate(self, guild_id: int | None) -> None:
        if guild_id is not None:
            self._settings_cache.pop(guild_id, None)

    async def _settings(self, guild_id: int) -> dict:
        cached = self._settings_cache.get(guild_id)
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        settings = await self._load_settings(guild_id)
        self._settings_cache[guild_id] = (time.monotonic(), settings)
        return settings

    async def _load_settings(self, guild_id: int) -> dict:
        row = await self.bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,))
        if row is None:
            await self.bot.db.execute("INSERT OR IGNORE INTO automod_settings(guild_id) VALUES (?)", (guild_id,))
            row = await self.bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    async def _update_json(self, interaction: discord.Interaction, field: str, value: int, add: bool) -> None:
        guild = interaction.guild
        if guild is None:
            return
        settings = await self._settings(guild.id)
        values = decode_json_list(settings.get(field))
        if add and value not in values:
            values.append(value)
        elif not add and value in values:
            values.remove(value)
        await self.bot.db.execute(
            f"UPDATE automod_settings SET {field} = ? WHERE guild_id = ?",
            (encode_json_list(values), guild.id),
        )
        self._invalidate(guild.id)

    @automod.command(name="enable", description="Enable automod protections for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def enable(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute(
            "INSERT INTO automod_settings(guild_id, enabled) VALUES (?, 1) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled = 1",
            (interaction.guild_id,),
        )
        self._invalidate(interaction.guild_id)
        await interaction.response.send_message(embed=success_embed("Automod enabled", "Protection checks are active."))

    @automod.command(name="disable", description="Disable automod protections for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def disable(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute(
            "INSERT INTO automod_settings(guild_id, enabled) VALUES (?, 0) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled = 0",
            (interaction.guild_id,),
        )
        self._invalidate(interaction.guild_id)
        await interaction.response.send_message(embed=success_embed("Automod disabled", "Automatic message checks are off."))

    @automod.command(name="config", description="View or change automod thresholds.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def config(
        self,
        interaction: discord.Interaction,
        spam_limit: app_commands.Range[int, 3, 20] | None = None,
        mention_limit: app_commands.Range[int, 3, 20] | None = None,
        punish_after: app_commands.Range[int, 1, 10] | None = None,
        timeout_seconds: app_commands.Range[int, 60, 2419200] | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        settings = await self._settings(guild.id)
        changes = {
            "spam_limit": spam_limit,
            "mention_limit": mention_limit,
            "punish_after": punish_after,
            "timeout_seconds": timeout_seconds,
        }
        for field, value in changes.items():
            if value is not None:
                await self.bot.db.execute(
                    f"UPDATE automod_settings SET {field} = ? WHERE guild_id = ?",
                    (value, guild.id),
                )
        self._invalidate(guild.id)
        settings = await self._settings(guild.id)
        embed = make_embed("Automod configuration")
        embed.add_field(name="Status", value="Enabled" if settings.get("enabled") else "Disabled")
        embed.add_field(name="Spam messages", value=f"{settings.get('spam_limit', 6)} per {settings.get('spam_window', 8)} seconds")
        embed.add_field(name="Mention limit", value=str(settings.get("mention_limit", 6)))
        embed.add_field(name="Timeout after violations", value=str(settings.get("punish_after", 3)))
        embed.add_field(name="Timeout length", value=f"{settings.get('timeout_seconds', 300)} seconds")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @whitelist.command(name="channel", description="Add or remove an automod-exempt channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def whitelist_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        remove: bool = False,
    ) -> None:
        await self._update_json(interaction, "whitelist_channels", channel.id, not remove)
        status = "removed from" if remove else "added to"
        await interaction.response.send_message(
            embed=success_embed("Automod whitelist updated", f"{channel.mention} was {status} the exempt channels."),
            ephemeral=True,
        )

    @whitelist.command(name="role", description="Add or remove a role exempt from automod.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def whitelist_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        remove: bool = False,
    ) -> None:
        await self._update_json(interaction, "whitelist_roles", role.id, not remove)
        status = "removed from" if remove else "added to"
        await interaction.response.send_message(
            embed=success_embed("Automod whitelist updated", f"{role.mention} was {status} the exempt roles."),
            ephemeral=True,
        )

    @blacklist.command(name="channel", description="Add or remove a channel where all messages are blocked.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def blacklist_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        remove: bool = False,
    ) -> None:
        await self._update_json(interaction, "blacklist_channels", channel.id, not remove)
        status = "removed from" if remove else "added to"
        await interaction.response.send_message(
            embed=success_embed("Automod channel list updated", f"{channel.mention} was {status} the blocked channels."),
            ephemeral=True,
        )

    @blacklist.command(name="word", description="Add or remove a blocked word.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def blacklist_word(
        self,
        interaction: discord.Interaction,
        word: app_commands.Range[str, 2, 40],
        remove: bool = False,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        settings = await self._settings(guild.id)
        values = [str(item).casefold() for item in decode_json_list(settings.get("blocked_words"))]
        normalized = word.strip().casefold()
        if remove:
            values = [item for item in values if item != normalized]
        elif normalized not in values:
            values.append(normalized)
        await self.bot.db.execute(
            "UPDATE automod_settings SET blocked_words = ? WHERE guild_id = ?",
            (json.dumps(values[:100], ensure_ascii=False), guild.id),
        )
        self._invalidate(guild.id)
        await interaction.response.send_message(
            embed=success_embed("Blocked words updated", f"`{normalized}` was {'removed from' if remove else 'added to'} the word filter."),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot or message.webhook_id:
            return
        if isinstance(message.author, discord.Member) and message.author.guild_permissions.manage_messages:
            return
        settings = await self._settings(message.guild.id)
        if not settings.get("enabled"):
            return
        if message.channel.id in decode_json_list(settings.get("whitelist_channels")):
            return
        if isinstance(message.author, discord.Member) and any(
            role.id in decode_json_list(settings.get("whitelist_roles")) for role in message.author.roles
        ):
            return
        if message.channel.id in decode_json_list(settings.get("blacklist_channels")):
            await self._apply_violation(message, "Messages are not allowed in this channel.", settings)
            return

        content = message.content.strip()
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        recent = self._message_events[key]
        while recent and now - recent[0][0] > int(settings.get("spam_window", 8)):
            recent.popleft()
        recent.append((now, content.casefold()))

        reason = None
        if len(recent) >= int(settings.get("spam_limit", 6)):
            reason = "Sending messages too quickly."
        elif len(content) >= 5 and sum(1 for _, previous in recent if previous == content.casefold()) >= 3:
            reason = "Repeated message detected."
        elif len(message.mentions) + len(message.role_mentions) >= int(settings.get("mention_limit", 6)):
            reason = "Too many member or role mentions."
        elif SUSPICIOUS_IP_URL.search(content):
            reason = "A link using a raw IP address was blocked."
        elif any(
            word and re.search(rf"(?<!\w){re.escape(str(word))}(?!\w)", content, re.IGNORECASE)
            for word in decode_json_list(settings.get("blocked_words"))
        ):
            reason = "A blocked word was detected."
        elif DISCORD_INVITE.search(content):
            reason = "Unapproved server invites are not allowed."

        if reason:
            await self._apply_violation(message, reason, settings)

    async def _apply_violation(self, message: discord.Message, reason: str, settings: dict) -> None:
        guild = message.guild
        if guild is None:
            return
        key = (guild.id, message.author.id)
        cooldown_until = self._action_cooldown.get(key, 0)
        now = time.monotonic()
        if now < cooldown_until:
            return
        self._action_cooldown[key] = now + 15
        if len(self._action_cooldown) > 5000:
            self._action_cooldown = {k: v for k, v in self._action_cooldown.items() if v > now}
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        self._violations[key] += 1
        count = self._violations[key]
        moderator_id = self.bot.user.id if self.bot.user else 0
        await self.bot.db.execute(
            """INSERT INTO moderation_logs
               (guild_id, moderator_id, target_id, action, reason)
               VALUES (?, ?, ?, 'automod', ?)""",
            (guild.id, moderator_id, message.author.id, reason[:500]),
        )
        if count >= int(settings.get("punish_after", 3)) and isinstance(message.author, discord.Member):
            bot_member = guild.me
            if bot_member and bot_member.guild_permissions.moderate_members and message.author.top_role < bot_member.top_role:
                try:
                    duration = int(settings.get("timeout_seconds", 300))
                    await message.author.timeout(discord.utils.utcnow() + timedelta(seconds=duration), reason=f"Automod: {reason}")
                    await self.bot.db.execute(
                        """INSERT INTO moderation_logs
                           (guild_id, moderator_id, target_id, action, reason, duration_seconds)
                           VALUES (?, ?, ?, 'automod_timeout', ?, ?)""",
                        (guild.id, moderator_id, message.author.id, reason[:500], duration),
                    )
                except discord.HTTPException:
                    logger.info("Automod timeout failed for user %s in guild %s", message.author.id, guild.id)
            self._violations[key] = 0
        log_row = await self.bot.db.fetchone(
            "SELECT channel_id, events FROM logging_settings WHERE guild_id = ?",
            (guild.id,),
        )
        log_events = decode_json_list(log_row["events"]) if log_row else []
        channel_id = log_row["channel_id"] if "moderation" in log_events else None
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    embed=make_embed("Automod action", f"{message.author.mention}: {reason}"),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        settings = await self._settings(member.guild.id)
        if not settings.get("enabled"):
            return
        count = self._join_events.add(member.guild.id, 0, int(settings.get("raid_window", 15)))
        if count < int(settings.get("raid_limit", 8)):
            return
        me = member.guild.me
        if me and me.guild_permissions.moderate_members and member.top_role < me.top_role:
            try:
                await member.timeout(discord.utils.utcnow() + timedelta(minutes=5), reason="Automod anti-raid threshold")
                await self.bot.db.execute(
                    """INSERT INTO moderation_logs
                       (guild_id, moderator_id, target_id, action, reason, duration_seconds)
                       VALUES (?, ?, ?, 'anti_raid_timeout', ?, ?)""",
                    (member.guild.id, self.bot.user.id if self.bot.user else 0, member.id, "Join-rate threshold reached.", 300),
                )
            except discord.HTTPException:
                logger.info("Anti-raid timeout failed in guild %s", member.guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutomodCog(bot))
