"""Public informational slash commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import BRAND_COLOR, make_embed


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check MyBot's response time.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            embed=make_embed("🏓 Pong", f"Gateway latency: **{latency_ms} ms**"),
            ephemeral=True,
        )

    @app_commands.command(name="serverinfo", description="Show useful information about this server.")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        humans = sum(not member.bot for member in guild.members)
        bots = guild.member_count - humans
        embed = make_embed(guild.name, guild.description or "No server description is set.")
        embed.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
        embed.add_field(name="Humans", value=f"{humans:,}", inline=True)
        embed.add_field(name="Bots", value=f"{bots:,}", inline=True)
        embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "D"), inline=True)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.owner:
            embed.set_footer(text=f"Owner: {guild.owner}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Show information about a server member.")
    @app_commands.guild_only()
    async def userinfo(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        target = member or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("This command requires a server member.", ephemeral=True)
            return
        embed = make_embed(str(target), f"Account created {discord.utils.format_dt(target.created_at, 'R')}.")
        embed.add_field(name="Joined", value=discord.utils.format_dt(target.joined_at, "R") if target.joined_at else "Unknown")
        embed.add_field(name="Top role", value=target.top_role.mention)
        embed.add_field(name="Roles", value=str(max(0, len(target.roles) - 1)))
        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Show a member's profile picture.")
    async def avatar(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        target = member or interaction.user
        embed = make_embed(f"{target.display_name}'s avatar")
        embed.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Browse everything MyBot can do.")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = make_embed("📖 MyBot command guide", "Type `/` and pick a command. Admin commands need the matching Discord permission.")
        sections = {
            "🛡️ Moderation": "`/ban` `/kick` `/timeout` `/untimeout` `/warn` `/warnings` `/clear` `/lock` `/unlock` `/slowmode` `/modlogs`",
            "🤖 Automod": "`/automod enable` `disable` `config` `whitelist` `blacklist`",
            "👋 Welcome": "`/welcome setup` `/goodbye setup` `/autorole`",
            "⭐ Leveling": "`/rank` `/leaderboard` `/level config` `/level reward`",
            "🎭 Roles": "`/role` `/reactionrole`",
            "🎫 Tickets": "`/ticket setup` `panel` `close` `add` `remove` `claim`",
            "🎁 Giveaways": "`/giveaway create` `end` `reroll` `list`",
            "💡 Suggestions": "`/suggest` `/suggestion config` `approve` `reject`",
            "🧠 AI & Knowledge": "Mention the bot to chat · `/ai` · `/knowledge`",
            "📊 Info": "`/serverinfo` `/userinfo` `/avatar` `/botinfo` `/analytics`",
        }
        for name, value in sections.items():
            embed.add_field(name=name, value=value, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="botinfo", description="Show MyBot's status and feature readiness.")
    async def botinfo(self, interaction: discord.Interaction) -> None:
        ai_ready = bool(getattr(getattr(self.bot, "ai", None), "enabled", False))
        db_ready = bool(getattr(getattr(self.bot, "db", None), "connected", False))
        embed = make_embed("MyBot status")
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)))
        embed.add_field(name="Database", value="Ready" if db_ready else "Unavailable")
        embed.add_field(name="AI provider", value="Configured" if ai_ready else "Not configured")
        embed.add_field(name="Loaded modules", value=str(len(self.bot.extensions)))
        embed.color = BRAND_COLOR
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
