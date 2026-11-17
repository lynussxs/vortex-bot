"""Suggestion submission, unique voting, and moderator review."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, make_embed, success_embed


class SuggestionView(discord.ui.View):
    def __init__(self, cog: "SuggestionsCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Support", style=discord.ButtonStyle.success, emoji="▲", custom_id="mybot:suggestion:up")
    async def upvote(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.vote(interaction, 1)

    @discord.ui.button(label="Oppose", style=discord.ButtonStyle.danger, emoji="▼", custom_id="mybot:suggestion:down")
    async def downvote(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.vote(interaction, -1)


class SuggestionsCog(commands.Cog):
    suggestion = app_commands.Group(name="suggestion", description="Configure and review community suggestions.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        rows = await self.bot.db.fetchall("SELECT message_id FROM suggestions WHERE status = 'pending'")
        for row in rows:
            self.bot.add_view(SuggestionView(self), message_id=row["message_id"])

    @app_commands.command(name="suggest", description="Submit a suggestion for this server.")
    @app_commands.guild_only()
    async def suggest(self, interaction: discord.Interaction, suggestion_text: app_commands.Range[str, 5, 1500]) -> None:
        guild = interaction.guild
        if guild is None:
            return
        row = await self.bot.db.fetchone(
            "SELECT suggestion_channel_id FROM guild_settings WHERE guild_id = ?",
            (guild.id,),
        )
        channel = guild.get_channel(row["suggestion_channel_id"]) if row and row["suggestion_channel_id"] else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Suggestions are not configured. Ask a server administrator to run /suggestion config."), ephemeral=True)
            return
        embed = self._embed(suggestion_text.strip(), interaction.user, 0, 0, "pending")
        message = await channel.send(embed=embed, view=SuggestionView(self))
        await self.bot.db.execute(
            """INSERT INTO suggestions(guild_id, channel_id, message_id, author_id, content)
               VALUES (?, ?, ?, ?, ?)""",
            (guild.id, channel.id, message.id, interaction.user.id, suggestion_text.strip()),
        )
        self.bot.add_view(SuggestionView(self), message_id=message.id)
        await interaction.response.send_message(embed=success_embed("Suggestion submitted", f"Your suggestion is in {channel.mention}."), ephemeral=True)

    @suggestion.command(name="config", description="Set or clear the suggestion channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def config(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.bot.db.execute(
            """INSERT INTO guild_settings(guild_id, suggestion_channel_id) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET suggestion_channel_id = excluded.suggestion_channel_id""",
            (interaction.guild_id, channel.id if channel else None),
        )
        await interaction.response.send_message(
            embed=success_embed("Suggestion channel updated", f"Suggestions will go to {channel.mention}." if channel else "Suggestions are disabled."),
            ephemeral=True,
        )

    async def vote(self, interaction: discord.Interaction, vote: int) -> None:
        row = await self.bot.db.fetchone(
            "SELECT id, content, author_id, status FROM suggestions WHERE message_id = ? AND guild_id = ?",
            (interaction.message.id, interaction.guild_id),
        )
        if not row or row["status"] != "pending":
            await interaction.response.send_message("This suggestion is no longer open for voting.", ephemeral=True)
            return
        suggestion_id = int(row["id"])
        async with self.bot.db.transaction() as connection:
            previous = await (await connection.execute(
                "SELECT vote FROM suggestion_votes WHERE suggestion_id = ? AND user_id = ?",
                (suggestion_id, interaction.user.id),
            )).fetchone()
            if previous and int(previous["vote"]) == vote:
                await connection.execute(
                    "DELETE FROM suggestion_votes WHERE suggestion_id = ? AND user_id = ?",
                    (suggestion_id, interaction.user.id),
                )
            else:
                await connection.execute(
                    """INSERT INTO suggestion_votes(suggestion_id, user_id, vote) VALUES (?, ?, ?)
                       ON CONFLICT(suggestion_id, user_id) DO UPDATE SET vote = excluded.vote""",
                    (suggestion_id, interaction.user.id, vote),
                )
        counts = await self.bot.db.fetchone(
            """SELECT SUM(CASE WHEN vote = 1 THEN 1 ELSE 0 END) AS upvotes,
                      SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END) AS downvotes
               FROM suggestion_votes WHERE suggestion_id = ?""",
            (suggestion_id,),
        )
        upvotes = int(counts["upvotes"] or 0) if counts else 0
        downvotes = int(counts["downvotes"] or 0) if counts else 0
        message = interaction.message
        embed = self._embed(str(row["content"]), interaction.guild.get_member(row["author_id"]) or f"<@{row['author_id']}>", upvotes, downvotes, str(row["status"]))
        await message.edit(embed=embed)
        await interaction.response.send_message("Your vote was recorded. You can change or remove it by clicking again.", ephemeral=True)

    @staticmethod
    def _embed(content: str, author: discord.abc.User, upvotes: int, downvotes: int, status: str) -> discord.Embed:
        embed = make_embed("Community suggestion", content)
        embed.add_field(name="Support", value=str(upvotes))
        embed.add_field(name="Oppose", value=str(downvotes))
        embed.add_field(name="Status", value=status.title())
        embed.set_footer(text=f"Submitted by {author}")
        return embed

    async def _review(self, interaction: discord.Interaction, message_id: str, status: str) -> None:
        try:
            parsed_id = int(message_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Message ID must be numeric."), ephemeral=True)
            return
        row = await self.bot.db.fetchone(
            "SELECT * FROM suggestions WHERE guild_id = ? AND message_id = ?",
            (interaction.guild_id, parsed_id),
        )
        if not row:
            await interaction.response.send_message(embed=error_embed("Suggestion not found."), ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE suggestions SET status = ? WHERE id = ?",
            (status, row["id"]),
        )
        counts = await self.bot.db.fetchone(
            """SELECT SUM(CASE WHEN vote = 1 THEN 1 ELSE 0 END) AS upvotes,
                      SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END) AS downvotes
               FROM suggestion_votes WHERE suggestion_id = ?""",
            (row["id"],),
        )
        channel = interaction.guild.get_channel(row["channel_id"])
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(parsed_id)
                author = interaction.guild.get_member(row["author_id"]) or f"<@{row['author_id']}>"
                embed = self._embed(row["content"], author, int(counts["upvotes"] or 0), int(counts["downvotes"] or 0), status)
                await message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass
        await interaction.response.send_message(embed=success_embed("Suggestion reviewed", f"Marked as **{status}**."), ephemeral=True)

    @suggestion.command(name="approve", description="Approve a suggestion by its message ID.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def approve(self, interaction: discord.Interaction, message_id: str) -> None:
        await self._review(interaction, message_id, "approved")

    @suggestion.command(name="reject", description="Reject a suggestion by its message ID.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def reject(self, interaction: discord.Interaction, message_id: str) -> None:
        await self._review(interaction, message_id, "rejected")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SuggestionsCog(bot))
