"""Per-server FAQ, rules, public metadata, and pinned announcement knowledge."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.ai_context import retrieve_knowledge
from core.embed_builder import error_embed, make_embed, success_embed
from utils.constants import KNOWLEDGE_ANSWER_LIMIT, KNOWLEDGE_QUESTION_LIMIT
from utils.validators import clean_text


class ClearKnowledgeView(discord.ui.View):
    def __init__(self, cog: "ServerKnowledgeCog", guild_id: int, requester_id: int) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.requester_id = requester_id

    @discord.ui.button(label="Confirm clear", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the administrator who requested this can confirm.", ephemeral=True)
            return
        await self.cog.bot.db.execute("DELETE FROM server_knowledge WHERE guild_id = ?", (self.guild_id,))
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=success_embed("Knowledge cleared", "All custom and synchronized knowledge entries were removed."),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the administrator who requested this can cancel.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=make_embed("Clear cancelled"), view=self)
        self.stop()


class ServerKnowledgeCog(commands.Cog):
    knowledge = app_commands.Group(name="knowledge", description="Manage verified information for this server.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @knowledge.command(name="add", description="Add or update a verified FAQ, rule, or announcement.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def add(
        self,
        interaction: discord.Interaction,
        question: app_commands.Range[str, 2, KNOWLEDGE_QUESTION_LIMIT],
        answer: app_commands.Range[str, 2, KNOWLEDGE_ANSWER_LIMIT],
        category: str,
    ) -> None:
        try:
            question = clean_text(question, KNOWLEDGE_QUESTION_LIMIT)
            answer = clean_text(answer, KNOWLEDGE_ANSWER_LIMIT)
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        existing = await self.bot.db.fetchone(
            "SELECT id FROM server_knowledge WHERE guild_id = ? AND lower(question) = lower(?) AND source = 'admin'",
            (interaction.guild_id, question),
        )
        if existing:
            await self.bot.db.execute(
                """UPDATE server_knowledge SET answer = ?, category = ?, approved = 1,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ? AND guild_id = ?""",
                (answer, category.casefold(), existing["id"], interaction.guild_id),
            )
            detail = "Updated the existing verified entry."
        else:
            await self.bot.db.execute(
                """INSERT INTO server_knowledge(guild_id, category, question, answer, source, approved)
                   VALUES (?, ?, ?, ?, 'admin', 1)""",
                (interaction.guild_id, category.casefold(), question, answer),
            )
            detail = "Added a verified entry."
        await interaction.response.send_message(embed=success_embed("Server knowledge saved", detail), ephemeral=True)

    @add.autocomplete("category")
    async def category_choices(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        options = [
            ("faq", "FAQ"),
            ("rules", "Rules"),
            ("announcement", "Announcement"),
            ("information", "Information"),
        ]
        return [
            app_commands.Choice(name=name, value=value)
            for value, name in options if current.casefold() in value.casefold() or current.casefold() in name.casefold()
        ][:25]

    @knowledge.command(name="remove", description="Remove a knowledge entry by its ID.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, entry_id: int) -> None:
        row = await self.bot.db.fetchone(
            "SELECT id FROM server_knowledge WHERE id = ? AND guild_id = ?",
            (entry_id, interaction.guild_id),
        )
        if not row:
            await interaction.response.send_message(embed=error_embed("Knowledge entry not found."), ephemeral=True)
            return
        await self.bot.db.execute(
            "DELETE FROM server_knowledge WHERE id = ? AND guild_id = ?",
            (entry_id, interaction.guild_id),
        )
        await interaction.response.send_message(embed=success_embed("Knowledge removed", f"Removed entry `{entry_id}`."), ephemeral=True)

    @knowledge.command(name="list", description="List verified server knowledge entries.")
    @app_commands.guild_only()
    async def list_entries(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            """SELECT id, category, question, source FROM server_knowledge
               WHERE guild_id = ? AND approved = 1 ORDER BY id DESC LIMIT 25""",
            (interaction.guild_id,),
        )
        embed = make_embed("Server knowledge")
        embed.description = "\n".join(
            f"`{row['id']}` · **{str(row['category']).title()}** · {str(row['question'])[:150]} · `{row['source']}`"
            for row in rows
        ) if rows else "No approved knowledge entries."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @knowledge.command(name="search", description="Search approved server knowledge.")
    @app_commands.guild_only()
    async def search(self, interaction: discord.Interaction, query: app_commands.Range[str, 2, 300]) -> None:
        rows = await retrieve_knowledge(self.bot.db, interaction.guild_id, query, limit=5)
        embed = make_embed("Knowledge search")
        if rows:
            for item in rows:
                embed.add_field(name=f"{item['category'].title()} · {item['question'][:240]}", value=item["answer"][:1000], inline=False)
        else:
            embed.description = "No matching verified information was found."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @knowledge.command(name="sync", description="Refresh server metadata and approved pinned public posts.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def sync(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.db.execute(
            "DELETE FROM server_knowledge WHERE guild_id = ? AND source = 'sync'",
            (guild.id,),
        )
        additions = [
            (guild.id, "information", "What is the server name?", guild.name[:300], "sync", None),
            (guild.id, "information", "What is the server description?", (guild.description or "No description is set.")[:KNOWLEDGE_ANSWER_LIMIT], "sync", None),
        ]
        public_text_channels = [
            channel for channel in guild.text_channels
            if channel.permissions_for(guild.default_role).view_channel
        ]
        if public_text_channels:
            names = ", ".join(f"#{channel.name}" for channel in public_text_channels[:60])
            additions.append((guild.id, "channels", "Which public text channels are available?", names[:KNOWLEDGE_ANSWER_LIMIT], "sync", None))
        public_roles = [role.name for role in guild.roles if not role.is_default() and not role.is_bot_managed()]
        if public_roles:
            additions.append((guild.id, "roles", "Which server roles are available?", ", ".join(public_roles[:60])[:KNOWLEDGE_ANSWER_LIMIT], "sync", None))

        synced_posts = 0
        for channel in public_text_channels:
            name = channel.name.casefold()
            if not any(term in name for term in ("rule", "faq", "announcement", "news")):
                continue
            permissions = channel.permissions_for(guild.me) if guild.me else discord.Permissions.none()
            if not permissions.read_message_history:
                continue
            try:
                pinned_messages = await channel.pins()
            except discord.HTTPException:
                continue
            category = (
                "rules" if "rule" in name else
                "faq" if "faq" in name else
                "announcement"
            )
            for pinned in pinned_messages[:10]:
                text = pinned.clean_content.strip()
                if not text:
                    continue
                additions.append((
                    guild.id,
                    category,
                    f"Pinned post in #{channel.name} ({pinned.id})",
                    text[:KNOWLEDGE_ANSWER_LIMIT],
                    "sync",
                    channel.id,
                ))
                synced_posts += 1
        async with self.bot.db.transaction() as connection:
            await connection.executemany(
                """INSERT INTO server_knowledge
                   (guild_id, category, question, answer, source, channel_id, approved)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                additions,
            )
        await interaction.followup.send(
            embed=success_embed(
                "Server knowledge synchronized",
                f"Saved {len(additions)} metadata and pinned-post entries; {synced_posts} pinned post(s) were imported. "
                "Private channels and unpinned message history were not read.",
            ),
            ephemeral=True,
        )

    @knowledge.command(name="clear", description="Clear all custom and synchronized server knowledge.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=make_embed("Confirm knowledge clear", "This permanently removes every knowledge entry for this server."),
            view=ClearKnowledgeView(self, interaction.guild_id, interaction.user.id),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerKnowledgeCog(bot))
