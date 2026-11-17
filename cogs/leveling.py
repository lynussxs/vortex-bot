"""Persistent message-based XP, rank cards, role rewards, and leaderboards."""

from __future__ import annotations

import math
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import GOLD_COLOR, error_embed, make_embed, success_embed
from core.permissions import bot_can_manage_role, is_protected_role
from utils.helpers import decode_json_list, encode_json_list


def level_for_xp(xp: int) -> int:
    return max(0, int(math.sqrt(max(0, xp) / 100)))


def xp_for_level(level: int) -> int:
    return level * level * 100


class LevelResetConfirmView(discord.ui.View):
    def __init__(
        self,
        cog: "LevelingCog",
        guild_id: int,
        requester_id: int,
        member_id: int | None,
    ) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.member_id = member_id

    @discord.ui.button(label="Confirm reset", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the administrator who started this reset can confirm it.", ephemeral=True)
            return
        if self.member_id is None:
            await self.cog.bot.db.execute("DELETE FROM user_levels WHERE guild_id = ?", (self.guild_id,))
            result = "All level data for this server was reset."
        else:
            await self.cog.bot.db.execute(
                "DELETE FROM user_levels WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.member_id),
            )
            result = f"Level data for <@{self.member_id}> was reset."
        button.disabled = True
        await interaction.response.edit_message(
            embed=success_embed("Level data reset", result),
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the administrator who started this reset can cancel it.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=make_embed("Reset cancelled"), view=self)
        self.stop()


class LevelingCog(commands.Cog):
    level = app_commands.Group(name="level", description="Configure XP, rewards, and progression.")
    reward = app_commands.Group(name="reward", description="Manage level-based role rewards.", parent=level)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_xp: dict[tuple[int, int], float] = {}
        self._settings_cache: dict[int, tuple[float, dict]] = {}

    async def _settings(self, guild_id: int) -> dict:
        cached = self._settings_cache.get(guild_id)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        await self.bot.db.execute("INSERT OR IGNORE INTO level_settings(guild_id) VALUES (?)", (guild_id,))
        row = await self.bot.db.fetchone("SELECT * FROM level_settings WHERE guild_id = ?", (guild_id,))
        settings = dict(row) if row else {}
        self._settings_cache[guild_id] = (time.monotonic(), settings)
        return settings

    @app_commands.command(name="rank", description="Show your or another member's rank.")
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        guild = interaction.guild
        target = member or interaction.user
        if guild is None:
            return
        row = await self.bot.db.fetchone(
            "SELECT xp, level FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild.id, target.id),
        )
        xp = int(row["xp"]) if row else 0
        level = level_for_xp(xp)
        start = xp_for_level(level)
        end = xp_for_level(level + 1)
        progress = 0 if end == start else int((xp - start) * 100 / (end - start))
        bar = "🟦" * (progress // 10) + "⬜" * (10 - progress // 10)
        leaderboard_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) + 1 AS rank FROM user_levels WHERE guild_id = ? AND xp > ?",
            (guild.id, xp),
        )
        position = int(leaderboard_row["rank"]) if leaderboard_row else 1
        embed = make_embed(f"{target.display_name}'s rank", f"Level **{level}** · **{xp:,} XP**")
        embed.add_field(name="Progress", value=f"{bar} {progress}%\n{xp - start:,} / {end - start:,} XP to next level", inline=False)
        embed.add_field(name="Server rank", value=f"🏆 #{position}")
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Show the server's top XP members.")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT user_id, xp FROM user_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT 10",
            (interaction.guild_id,),
        )
        embed = make_embed("🏆 Level leaderboard", color=GOLD_COLOR)
        if not rows:
            embed.description = "No XP has been earned yet."
        else:
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            embed.description = "\n".join(
                f"{medals.get(index, f'`#{index}`')} <@{row['user_id']}> — **{row['xp']:,} XP** · Level {level_for_xp(row['xp'])}"
                for index, row in enumerate(rows, 1)
            )
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @level.command(name="config", description="View or change XP multiplier and cooldown.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def config(
        self,
        interaction: discord.Interaction,
        multiplier: app_commands.Range[float, 0.1, 5.0] | None = None,
        cooldown_seconds: app_commands.Range[int, 10, 3600] | None = None,
        announce_channel: discord.TextChannel | None = None,
        ignored_channel: discord.TextChannel | None = None,
        ignore_channel: bool = False,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        settings = await self._settings(guild.id)
        if multiplier is not None:
            await self.bot.db.execute("UPDATE level_settings SET multiplier = ? WHERE guild_id = ?", (multiplier, guild.id))
        if cooldown_seconds is not None:
            await self.bot.db.execute("UPDATE level_settings SET cooldown_seconds = ? WHERE guild_id = ?", (cooldown_seconds, guild.id))
        if announce_channel is not None:
            await self.bot.db.execute(
                "UPDATE level_settings SET announce_channel_id = ? WHERE guild_id = ?",
                (announce_channel.id, guild.id),
            )
        ignored = decode_json_list(settings.get("ignored_channels"))
        if ignored_channel:
            if ignore_channel and ignored_channel.id in ignored:
                ignored.remove(ignored_channel.id)
            elif not ignore_channel and ignored_channel.id not in ignored:
                ignored.append(ignored_channel.id)
            await self.bot.db.execute(
                "UPDATE level_settings SET ignored_channels = ? WHERE guild_id = ?",
                (encode_json_list(ignored), guild.id),
            )
        self._settings_cache.pop(guild.id, None)
        updated = await self._settings(guild.id)
        ignored_names = [f"<#{channel_id}>" for channel_id in decode_json_list(updated.get("ignored_channels"))]
        embed = make_embed("Leveling settings")
        embed.add_field(name="XP multiplier", value=str(updated.get("multiplier", 1.0)))
        embed.add_field(name="XP cooldown", value=f"{updated.get('cooldown_seconds', 60)} seconds")
        announce_id = updated.get("announce_channel_id")
        announce = guild.get_channel(announce_id) if announce_id else None
        embed.add_field(name="Level-up channel", value=announce.mention if announce else "Current message channel")
        embed.add_field(name="Ignored channels", value=", ".join(ignored_names) if ignored_names else "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reward.command(name="add", description="Give a role when members reach a level.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def reward_add(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 1, 1000],
        role: discord.Role,
    ) -> None:
        if role.is_default() or is_protected_role(role) or not bot_can_manage_role(interaction.guild, role):
            await interaction.response.send_message(embed=error_embed("That reward role is protected or above MyBot's role."), ephemeral=True)
            return
        await self.bot.db.execute(
            """INSERT INTO level_rewards(guild_id, level, role_id) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id""",
            (interaction.guild_id, level, role.id),
        )
        await interaction.response.send_message(embed=success_embed("Level reward saved", f"Members reaching level {level} receive {role.mention}."), ephemeral=True)

    @reward.command(name="remove", description="Remove a role reward for a level.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def reward_remove(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 1000]) -> None:
        await self.bot.db.execute(
            "DELETE FROM level_rewards WHERE guild_id = ? AND level = ?",
            (interaction.guild_id, level),
        )
        await interaction.response.send_message(embed=success_embed("Level reward removed", f"Removed the reward for level {level}."), ephemeral=True)

    @level.command(name="reset", description="Reset one member's XP or all XP for this server.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def reset(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        target = f"{member.mention}" if member else "all members"
        view = LevelResetConfirmView(self, interaction.guild_id, interaction.user.id, member.id if member else None)
        await interaction.response.send_message(
            embed=make_embed("Confirm level reset", f"This permanently resets level data for **{target}**."),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot or message.webhook_id or not message.content.strip():
            return
        settings = await self._settings(message.guild.id)
        if message.channel.id in decode_json_list(settings.get("ignored_channels")):
            return
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        old = await self.bot.db.fetchone(
            "SELECT xp, level, last_xp_at FROM user_levels WHERE guild_id = ? AND user_id = ?",
            key,
        )
        cooldown = int(settings.get("cooldown_seconds", 60))
        if key in self._last_xp:
            if now - self._last_xp[key] < cooldown:
                return
        elif old and int(time.time()) - int(old["last_xp_at"]) < cooldown:
            self._last_xp[key] = now - max(0, int(time.time()) - int(old["last_xp_at"]))
            return
        self._last_xp[key] = now
        gained = max(1, int(random.randint(15, 25) * float(settings.get("multiplier", 1.0))))
        old_level = int(old["level"]) if old else 0
        await self.bot.db.execute(
            """INSERT INTO user_levels(guild_id, user_id, xp, level, last_xp_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   xp = user_levels.xp + excluded.xp,
                   level = user_levels.level,
                   last_xp_at = excluded.last_xp_at""",
            (message.guild.id, message.author.id, gained, 0, int(time.time())),
        )
        current = await self.bot.db.fetchone(
            "SELECT xp FROM user_levels WHERE guild_id = ? AND user_id = ?",
            key,
        )
        total_xp = int(current["xp"]) if current else gained
        new_level = level_for_xp(total_xp)
        if new_level <= old_level:
            return
        await self.bot.db.execute(
            "UPDATE user_levels SET level = ? WHERE guild_id = ? AND user_id = ?",
            (new_level, *key),
        )
        rewards = await self.bot.db.fetchall(
            "SELECT role_id FROM level_rewards WHERE guild_id = ? AND level > ? AND level <= ?",
            (message.guild.id, old_level, new_level),
        )
        member = message.author
        if isinstance(member, discord.Member) and message.guild.me and message.guild.me.guild_permissions.manage_roles:
            roles = [
                role for row in rewards
                if (role := message.guild.get_role(row["role_id"]))
                and bot_can_manage_role(message.guild, role)
            ]
            if roles:
                try:
                    await member.add_roles(*roles, reason=f"Reached level {new_level}")
                except discord.HTTPException:
                    pass
        channel_id = settings.get("announce_channel_id")
        channel = message.guild.get_channel(channel_id) if channel_id else message.channel
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    f"{message.author.mention} reached **level {new_level}**!",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LevelingCog(bot))
