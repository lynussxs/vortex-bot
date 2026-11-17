"""Welcome, goodbye, and automatic member-role configuration."""

from __future__ import annotations

import random
import re

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, make_embed, success_embed
from core.permissions import is_protected_role
from utils.validators import clean_text


class WelcomeCog(commands.Cog):
    welcome = app_commands.Group(name="welcome", description="Configure new-member welcome messages.")
    goodbye = app_commands.Group(name="goodbye", description="Configure member departure messages.")
    autorole = app_commands.Group(name="autorole", description="Manage roles assigned to new members.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _settings(self, guild_id: int) -> dict:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO welcome_settings(guild_id) VALUES (?)",
            (guild_id,),
        )
        row = await self.bot.db.fetchone("SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,))
        return dict(row) if row else {}

    @staticmethod
    def _render(template: str, member: discord.Member) -> str:
        variants = [value.strip() for value in template.split("||") if value.strip()]
        chosen = random.choice(variants) if variants else template
        values = {
            "user": member.mention,
            "username": discord.utils.escape_markdown(member.display_name)[:100],
            "server": discord.utils.escape_markdown(member.guild.name)[:100],
            "membercount": str(member.guild.member_count or 0),
            "userid": str(member.id),
        }
        # Replace only known {placeholders}; unknown braces stay literal instead of crashing.
        rendered = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), chosen)
        return rendered[:1900]

    @welcome.command(name="setup", description="Set the welcome channel and optional message template.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(template="Place multiple rotating templates here, separated with ||.")
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        template: app_commands.Range[str, 1, 1000] | None = None,
    ) -> None:
        try:
            clean_template = clean_text(
                template or "Welcome {user} to {server}! You are member #{membercount}.",
                1000,
            )
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        await self.bot.db.execute(
            """INSERT INTO welcome_settings(guild_id, welcome_channel_id, welcome_enabled, welcome_template)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(guild_id) DO UPDATE SET welcome_channel_id = excluded.welcome_channel_id,
                   welcome_enabled = 1, welcome_template = excluded.welcome_template""",
            (interaction.guild_id, channel.id, clean_template),
        )
        await interaction.response.send_message(
            embed=success_embed("Welcome messages enabled", f"New members will be welcomed in {channel.mention}."),
            ephemeral=True,
        )

    @welcome.command(name="disable", description="Turn off welcome messages.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def welcome_disable(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute(
            "INSERT INTO welcome_settings(guild_id, welcome_enabled) VALUES (?, 0) "
            "ON CONFLICT(guild_id) DO UPDATE SET welcome_enabled = 0",
            (interaction.guild_id,),
        )
        await interaction.response.send_message(embed=success_embed("Welcome messages disabled", "New members will not receive a welcome post."), ephemeral=True)

    @welcome.command(name="config", description="Show the current welcome message settings.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def welcome_config(self, interaction: discord.Interaction) -> None:
        settings = await self._settings(interaction.guild_id)
        channel_id = settings.get("welcome_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        embed = make_embed("Welcome settings")
        embed.add_field(name="Status", value="Enabled" if settings.get("welcome_enabled") else "Disabled")
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set")
        embed.add_field(name="Template", value=str(settings.get("welcome_template", ""))[:1000], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome.command(name="test", description="Preview the welcome message in its configured channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def welcome_test(self, interaction: discord.Interaction) -> None:
        settings = await self._settings(interaction.guild_id)
        channel_id = settings.get("welcome_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Set a welcome channel first with /welcome setup."), ephemeral=True)
            return
        message = self._render(str(settings.get("welcome_template", "")), interaction.user)
        embed = make_embed("Welcome", message)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        await interaction.response.send_message(embed=success_embed("Test sent", f"Check {channel.mention}."), ephemeral=True)

    @goodbye.command(name="setup", description="Set the goodbye channel and optional message template.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(template="Place multiple rotating templates here, separated with ||.")
    async def goodbye_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        template: app_commands.Range[str, 1, 1000] | None = None,
    ) -> None:
        clean_template = clean_text(
            template or "{username} has left {server}.",
            1000,
        )
        await self.bot.db.execute(
            """INSERT INTO welcome_settings(guild_id, goodbye_channel_id, goodbye_enabled, goodbye_template)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(guild_id) DO UPDATE SET goodbye_channel_id = excluded.goodbye_channel_id,
                   goodbye_enabled = 1, goodbye_template = excluded.goodbye_template""",
            (interaction.guild_id, channel.id, clean_template),
        )
        await interaction.response.send_message(
            embed=success_embed("Goodbye messages enabled", f"Departures will be posted in {channel.mention}."),
            ephemeral=True,
        )

    @goodbye.command(name="disable", description="Turn off goodbye messages.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def goodbye_disable(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute(
            "INSERT INTO welcome_settings(guild_id, goodbye_enabled) VALUES (?, 0) "
            "ON CONFLICT(guild_id) DO UPDATE SET goodbye_enabled = 0",
            (interaction.guild_id,),
        )
        await interaction.response.send_message(embed=success_embed("Goodbye messages disabled", "Member departures will not be posted."), ephemeral=True)

    @autorole.command(name="add", description="Assign a role automatically when a member joins.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def autorole_add(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if role.is_default() or is_protected_role(role) or role.managed:
            await interaction.response.send_message(embed=error_embed("That role cannot be assigned automatically."), ephemeral=True)
            return
        if interaction.guild.me is None or role >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=error_embed("Move Vortex's highest role above the autorole."), ephemeral=True)
            return
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO autoroles(guild_id, role_id) VALUES (?, ?)",
            (interaction.guild_id, role.id),
        )
        await interaction.response.send_message(embed=success_embed("Autorole added", f"{role.mention} will be assigned to new members."), ephemeral=True)

    @autorole.command(name="remove", description="Stop assigning a role to new members.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def autorole_remove(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self.bot.db.execute(
            "DELETE FROM autoroles WHERE guild_id = ? AND role_id = ?",
            (interaction.guild_id, role.id),
        )
        await interaction.response.send_message(embed=success_embed("Autorole removed", f"{role.mention} will no longer be assigned."), ephemeral=True)

    @autorole.command(name="list", description="List the roles assigned to new members.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def autorole_list(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM autoroles WHERE guild_id = ? ORDER BY role_id",
            (interaction.guild_id,),
        )
        role_mentions = [role.mention for row in rows if (role := interaction.guild.get_role(row["role_id"]))]
        embed = make_embed("Automatic member roles", "\n".join(role_mentions) if role_mentions else "No autoroles configured.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM autoroles WHERE guild_id = ?",
            (member.guild.id,),
        )
        roles = []
        bot_member = member.guild.me
        for row in rows:
            role = member.guild.get_role(row["role_id"])
            if role and bot_member and role < bot_member.top_role and not role.managed:
                roles.append(role)
        if roles and bot_member and bot_member.guild_permissions.manage_roles:
            try:
                await member.add_roles(*roles, reason="Vortex autorole")
            except discord.HTTPException:
                pass

        settings = await self.bot.db.fetchone(
            "SELECT welcome_channel_id, welcome_template, welcome_enabled FROM welcome_settings WHERE guild_id = ?",
            (member.guild.id,),
        )
        if not settings or not settings["welcome_enabled"] or not settings["welcome_channel_id"]:
            return
        channel = member.guild.get_channel(settings["welcome_channel_id"])
        if isinstance(channel, discord.TextChannel):
            try:
                text = self._render(settings["welcome_template"], member)
                embed = make_embed("Welcome", text)
                embed.set_thumbnail(url=member.display_avatar.url)
                await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        settings = await self.bot.db.fetchone(
            "SELECT goodbye_channel_id, goodbye_template, goodbye_enabled FROM welcome_settings WHERE guild_id = ?",
            (member.guild.id,),
        )
        if not settings or not settings["goodbye_enabled"] or not settings["goodbye_channel_id"]:
            return
        channel = member.guild.get_channel(settings["goodbye_channel_id"])
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    self._render(settings["goodbye_template"], member),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
