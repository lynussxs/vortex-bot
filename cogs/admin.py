"""Owner-only operational commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, make_embed, success_embed


class AdminCog(commands.Cog):
    admin = app_commands.Group(name="admin", description="Owner-only bot operations.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _is_owner(self, interaction: discord.Interaction) -> bool:
        owner_id = self.bot.settings.owner_id
        if owner_id is None or interaction.user.id != owner_id:
            await interaction.response.send_message(embed=error_embed("This command is restricted to the configured bot owner."), ephemeral=True)
            return False
        return True

    @admin.command(name="status", description="Show operational status for the bot instance.")
    async def status(self, interaction: discord.Interaction) -> None:
        if not await self._is_owner(interaction):
            return
        embed = make_embed("Vortex operational status")
        embed.add_field(name="Bot", value=f"{self.bot.user} · `{self.bot.user.id}`" if self.bot.user else "Connecting")
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)))
        embed.add_field(name="Loaded cogs", value=str(len(self.bot.extensions)))
        embed.add_field(name="Slash commands", value=str(len(self.bot.tree.get_commands())))
        embed.add_field(name="SQLite", value="Connected" if self.bot.db.connected else "Unavailable")
        embed.add_field(name="OpenRouter", value="Configured" if self.bot.ai.enabled else "Not configured")
        embed.add_field(name="Database file", value=str(self.bot.settings.database_path)[:200], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin.command(name="sync", description="Manually synchronize slash commands.")
    async def sync(self, interaction: discord.Interaction) -> None:
        if not await self._is_owner(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.bot.settings.dev_guild_id:
            guild = discord.Object(id=self.bot.settings.dev_guild_id)
            self.bot.tree.copy_global_to(guild=guild)
            commands_synced = await self.bot.tree.sync(guild=guild)
        else:
            commands_synced = await self.bot.tree.sync()
        await interaction.followup.send(
            embed=success_embed("Commands synchronized", f"Updated {len(commands_synced)} command(s)."),
            ephemeral=True,
        )

    @admin.command(name="cleanup", description="Remove duplicate server-only slash commands from this server.")
    async def cleanup(self, interaction: discord.Interaction) -> None:
        if not await self._is_owner(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=error_embed("Run this inside a server."), ephemeral=True)
            return
        if self.bot.settings.dev_guild_id == guild.id:
            await interaction.response.send_message(
                embed=error_embed("This is the development server, whose commands are server-only on purpose. Remove DEV_GUILD_ID from the environment to switch to global commands, then run this."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        self.bot.tree.clear_commands(guild=guild)
        await self.bot.tree.sync(guild=guild)
        await interaction.followup.send(
            embed=success_embed("Duplicates removed", "Server-only commands were cleared. Only the global commands remain. Press Ctrl+R in Discord if the list still looks old."),
            ephemeral=True,
        )

    @admin.command(name="reload", description="Reload a loaded feature cog.")
    async def reload(self, interaction: discord.Interaction, cog: str) -> None:
        if not await self._is_owner(interaction):
            return
        extension = f"cogs.{cog.strip().casefold()}"
        if extension not in self.bot.extensions:
            await interaction.response.send_message(embed=error_embed("That cog is not loaded."), ephemeral=True)
            return
        try:
            await self.bot.reload_extension(extension)
        except Exception as exc:
            await interaction.response.send_message(embed=error_embed(f"Reload failed: {str(exc)[:250]}"), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Cog reloaded", f"`{extension}` was reloaded."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
