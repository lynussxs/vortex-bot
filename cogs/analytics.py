"""Lightweight event-based member and message analytics."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import make_embed
from utils.helpers import utc_day

logger = logging.getLogger("vortex.analytics")


class AnalyticsCog(commands.Cog):
    analytics = app_commands.Group(name="analytics", description="View server member and activity statistics.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._pending: dict[tuple[int, str, str], int] = defaultdict(int)
        self._flush_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def cog_unload(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.flush()
            except Exception:
                logger.exception("Could not persist the latest analytics batch.")

    async def flush(self) -> None:
        if not self._pending:
            return
        batch = [(guild_id, day, event, count) for (guild_id, day, event), count in self._pending.items()]
        self._pending.clear()
        try:
            async with self.bot.db.transaction() as connection:
                for guild_id, day, event, count in batch:
                    await connection.execute(
                        f"""INSERT INTO analytics_daily(guild_id, day, {event})
                            VALUES (?, ?, ?)
                            ON CONFLICT(guild_id, day) DO UPDATE SET {event} = {event} + excluded.{event}""",
                        (guild_id, day, count),
                    )
        except Exception:
            for guild_id, day, event, count in batch:
                self._pending[(guild_id, day, event)] += count
            raise

    def _record(self, guild_id: int, event: str, amount: int = 1) -> None:
        if event not in {"messages", "joins", "leaves"}:
            return
        self._pending[(guild_id, utc_day(), event)] += amount

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild and not message.author.bot and not message.webhook_id:
            self._record(message.guild.id, "messages")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        self._record(member.guild.id, "joins")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        self._record(member.guild.id, "leaves")

    @analytics.command(name="overview", description="Show a short overview of this server's activity.")
    @app_commands.guild_only()
    async def overview(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        rows = await self.bot.db.fetchall(
            """SELECT COALESCE(SUM(joins), 0) AS joins, COALESCE(SUM(leaves), 0) AS leaves,
                      COALESCE(SUM(messages), 0) AS messages
               FROM analytics_daily WHERE guild_id = ? AND day >= date('now', '-6 days')""",
            (guild.id,),
        )
        recent = rows[0] if rows else {"joins": 0, "leaves": 0, "messages": 0}
        moderation = await self.bot.db.fetchone(
            """SELECT COUNT(*) AS actions FROM moderation_logs
               WHERE guild_id = ? AND created_at >= datetime('now', '-6 days')""",
            (guild.id,),
        )
        humans = sum(not member.bot for member in guild.members)
        bots = sum(member.bot for member in guild.members)
        embed = make_embed(f"{guild.name} analytics", "Counts reflect available Discord events; data starts when Vortex is added.")
        embed.add_field(name="Members", value=f"{guild.member_count or 0:,}")
        embed.add_field(name="Humans", value=f"{humans:,}")
        embed.add_field(name="Bots", value=f"{bots:,}")
        embed.add_field(name="7-day joins", value=str(recent["joins"]))
        embed.add_field(name="7-day leaves", value=str(recent["leaves"]))
        embed.add_field(name="7-day messages", value=str(recent["messages"]))
        embed.add_field(name="7-day moderation actions", value=str(moderation["actions"] if moderation else 0), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @analytics.command(name="members", description="Show member counts and recent join or leave trends.")
    @app_commands.guild_only()
    async def members(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        rows = await self.bot.db.fetchall(
            """SELECT day, joins, leaves FROM analytics_daily WHERE guild_id = ?
               AND day >= date('now', '-6 days') ORDER BY day""",
            (guild.id,),
        )
        embed = make_embed("Member trends")
        if rows:
            embed.description = "\n".join(
                f"**{row['day']}** · +{row['joins']} joined · −{row['leaves']} left"
                for row in rows
            )
        else:
            embed.description = "No join or leave history is available yet."
        embed.add_field(name="Current members", value=f"{guild.member_count or 0:,}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @analytics.command(name="activity", description="Show message activity for the last seven days.")
    @app_commands.guild_only()
    async def activity(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            """SELECT day, messages FROM analytics_daily WHERE guild_id = ?
               AND day >= date('now', '-6 days') ORDER BY day""",
            (interaction.guild_id,),
        )
        embed = make_embed("Message activity")
        if rows:
            embed.description = "\n".join(
                f"**{row['day']}** · {row['messages']:,} message(s)"
                for row in rows
            )
        else:
            embed.description = "No message activity is available yet."
        embed.set_footer(text="Requires Message Content Intent. Vortex counts message events without storing message text.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnalyticsCog(bot))
