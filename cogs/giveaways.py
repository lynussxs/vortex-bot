"""Button-entry giveaways with restart recovery and auditable winner draws."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, make_embed, success_embed
from utils.helpers import discord_timestamp
from utils.validators import parse_duration


class GiveawayView(discord.ui.View):
    def __init__(self, cog: "GiveawaysCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Enter giveaway", style=discord.ButtonStyle.success, custom_id="mybot:giveaway:enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild_id or interaction.user.bot:
            await interaction.response.send_message("Only server members can enter.", ephemeral=True)
            return
        row = await self.cog.bot.db.fetchone(
            "SELECT id, ended FROM giveaways WHERE message_id = ?",
            (interaction.message.id,),
        )
        if not row or row["ended"]:
            await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
            return
        existing = await self.cog.bot.db.fetchone(
            "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (row["id"], interaction.user.id),
        )
        if existing:
            await self.cog.bot.db.execute(
                "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (row["id"], interaction.user.id),
            )
            response = "You left the giveaway."
        else:
            await self.cog.bot.db.execute(
                "INSERT OR IGNORE INTO giveaway_entries(giveaway_id, user_id) VALUES (?, ?)",
                (row["id"], interaction.user.id),
            )
            response = "You are entered. Click again to leave."
        await interaction.response.send_message(response, ephemeral=True)


class GiveawaysCog(commands.Cog):
    giveaway = app_commands.Group(name="giveaway", description="Create and manage giveaways.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._tasks: dict[int, asyncio.Task] = {}
        self._random = random.SystemRandom()

    async def cog_load(self) -> None:
        self.bot.add_view(GiveawayView(self))
        rows = await self.bot.db.fetchall("SELECT id, ends_at FROM giveaways WHERE ended = 0")
        for row in rows:
            self._schedule(int(row["id"]), str(row["ends_at"]))

    def cog_unload(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    def _schedule(self, giveaway_id: int, ends_at: str) -> None:
        if giveaway_id in self._tasks:
            self._tasks[giveaway_id].cancel()
        try:
            end = datetime.fromisoformat(ends_at).replace(tzinfo=timezone.utc)
        except ValueError:
            end = discord.utils.utcnow()
        delay = max(0, (end - discord.utils.utcnow()).total_seconds())
        self._tasks[giveaway_id] = asyncio.create_task(self._wait_and_finish(giveaway_id, delay))

    async def _wait_and_finish(self, giveaway_id: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self.finish(giveaway_id)
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(giveaway_id, None)

    @giveaway.command(name="create", description="Start a giveaway in a channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def create(
        self,
        interaction: discord.Interaction,
        prize: app_commands.Range[str, 1, 150],
        duration: str,
        winners: app_commands.Range[int, 1, 20] = 1,
        channel: discord.TextChannel | None = None,
    ) -> None:
        try:
            seconds = parse_duration(duration)
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        guild = interaction.guild
        target_channel = channel or interaction.channel
        if not guild or not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Choose a text channel."), ephemeral=True)
            return
        ends_at = discord.utils.utcnow().timestamp() + seconds
        end_iso = datetime.fromtimestamp(ends_at, tz=timezone.utc).isoformat()
        embed = self._giveaway_embed(prize, winners, int(ends_at), 0, False)
        message = await target_channel.send(embed=embed, view=GiveawayView(self))
        giveaway_id = await self.bot.db.execute(
            """INSERT INTO giveaways(guild_id, channel_id, message_id, prize, winner_count, ends_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (guild.id, target_channel.id, message.id, prize.strip(), winners, end_iso, interaction.user.id),
        )
        self._schedule(giveaway_id, end_iso)
        await interaction.response.send_message(embed=success_embed("Giveaway started", f"{message.jump_url}\nEnds {discord_timestamp(int(ends_at))}."), ephemeral=True)

    @staticmethod
    def _giveaway_embed(prize: str, winners: int, ends_at: int, entries: int, ended: bool) -> discord.Embed:
        embed = make_embed("Giveaway ended" if ended else "Giveaway", f"**Prize:** {prize}")
        embed.add_field(name="Winners", value=str(winners))
        embed.add_field(name="Entries", value=str(entries))
        embed.add_field(name="Ends", value=discord_timestamp(ends_at))
        embed.set_footer(text="Giveaway ended" if ended else "Click the button to enter")
        return embed

    async def finish(self, giveaway_id: int, *, reroll: bool = False) -> list[int]:
        async with self.bot.db.transaction() as connection:
            row_cursor = await connection.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
            row = await row_cursor.fetchone()
            await row_cursor.close()
            if not row or (row["ended"] and not reroll) or (reroll and not row["ended"]):
                return []
            entries_cursor = await connection.execute(
                "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?",
                (giveaway_id,),
            )
            entries = await entries_cursor.fetchall()
            await entries_cursor.close()
            draw_number = 1
            excluded: set[int] = set()
            if reroll:
                previous_draw = await (await connection.execute(
                    "SELECT MAX(draw_number) AS draw_number FROM giveaway_winners WHERE giveaway_id = ?",
                    (giveaway_id,),
                )).fetchone()
                draw_number = int(previous_draw["draw_number"] or 0) + 1
                previous = await connection.execute(
                    "SELECT user_id FROM giveaway_winners WHERE giveaway_id = ? AND draw_number = ?",
                    (giveaway_id, draw_number - 1),
                )
                excluded = {int(item["user_id"]) for item in await previous.fetchall()}
                await previous.close()
            candidate_ids = [
                int(item["user_id"]) for item in entries
                if int(item["user_id"]) not in excluded
            ]
            count = min(int(row["winner_count"]), len(candidate_ids))
            selected = self._random.sample(candidate_ids, count) if count else []
            if not reroll:
                await connection.execute("UPDATE giveaways SET ended = 1 WHERE id = ? AND ended = 0", (giveaway_id,))
            if selected:
                await connection.executemany(
                    "INSERT INTO giveaway_winners(giveaway_id, user_id, draw_number) VALUES (?, ?, ?)",
                    [(giveaway_id, user_id, draw_number) for user_id in selected],
                )
            entry_count = len(entries)
            giveaway = dict(row)
        channel = self.bot.get_channel(row["channel_id"])
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(row["message_id"])
                end_time = int(datetime.fromisoformat(row["ends_at"]).replace(tzinfo=timezone.utc).timestamp())
                await message.edit(
                    embed=self._giveaway_embed(str(row["prize"]), int(row["winner_count"]), end_time, entry_count, True),
                    view=None,
                )
                if selected:
                    mentions = ", ".join(f"<@{user_id}>" for user_id in selected)
                    text = f"Congratulations {mentions}! You won **{giveaway['prize']}**."
                    allowed = discord.AllowedMentions(users=[discord.Object(id=user_id) for user_id in selected])
                else:
                    text = "The giveaway ended with no eligible entries." if not reroll else "No new eligible winners were available."
                    allowed = discord.AllowedMentions.none()
                await channel.send(text, allowed_mentions=allowed)
            except discord.HTTPException:
                pass
        return selected

    @giveaway.command(name="end", description="End a giveaway early using its message ID.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def end(self, interaction: discord.Interaction, message_id: str) -> None:
        try:
            message = int(message_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Message ID must be numeric."), ephemeral=True)
            return
        row = await self.bot.db.fetchone("SELECT id FROM giveaways WHERE guild_id = ? AND message_id = ?", (interaction.guild_id, message))
        if not row:
            await interaction.response.send_message(embed=error_embed("Giveaway not found."), ephemeral=True)
            return
        task = self._tasks.pop(int(row["id"]), None)
        if task:
            task.cancel()
        winners = await self.finish(int(row["id"]))
        await interaction.response.send_message(embed=success_embed("Giveaway ended", f"Selected {len(winners)} winner(s)."), ephemeral=True)

    @giveaway.command(name="reroll", description="Draw a replacement winner for an ended giveaway.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def reroll(self, interaction: discord.Interaction, message_id: str) -> None:
        try:
            message = int(message_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Message ID must be numeric."), ephemeral=True)
            return
        row = await self.bot.db.fetchone(
            "SELECT id, ended FROM giveaways WHERE guild_id = ? AND message_id = ?",
            (interaction.guild_id, message),
        )
        if not row or not row["ended"]:
            await interaction.response.send_message(embed=error_embed("Only an ended giveaway can be rerolled."), ephemeral=True)
            return
        winners = await self.finish(int(row["id"]), reroll=True)
        await interaction.response.send_message(embed=success_embed("Giveaway rerolled", f"Selected {len(winners)} replacement winner(s)."), ephemeral=True)

    @giveaway.command(name="list", description="List current and recent giveaways.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def list_giveaways(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT message_id, prize, ends_at, ended FROM giveaways WHERE guild_id = ? ORDER BY id DESC LIMIT 10",
            (interaction.guild_id,),
        )
        embed = make_embed("Giveaways")
        embed.description = "\n".join(
            f"{'Ended' if row['ended'] else 'Active'} · `{row['message_id']}` · {row['prize'][:80]} · {row['ends_at']}"
            for row in rows
        ) if rows else "No giveaways found."
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GiveawaysCog(bot))
