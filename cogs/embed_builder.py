"""Saved, validated custom embeds for administrators."""

from __future__ import annotations

import json
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, success_embed
from utils.helpers import decode_json_list
from utils.validators import clean_text, valid_http_url


def parse_fields(value: str | None) -> list[dict[str, str]]:
    if not value or not value.strip():
        return []
    fields = []
    for piece in value.split(";"):
        if not piece.strip():
            continue
        parts = piece.split("|", 1)
        if len(parts) != 2:
            raise ValueError("Fields must use `name|value`, separated by semicolons.")
        name = clean_text(parts[0], 256)
        content = clean_text(parts[1], 1024)
        fields.append({"name": name, "value": content})
    if len(fields) > 25:
        raise ValueError("Embeds support up to 25 fields.")
    return fields


def render_embed(data: dict) -> discord.Embed:
    title = clean_text(str(data.get("title", "")), 256)
    description = clean_text(str(data.get("description", "")), 4096, allow_empty=True)
    embed = discord.Embed(
        title=title,
        description=description or None,
        color=discord.Color(int(data.get("color", 5793266))),
        timestamp=discord.utils.utcnow() if data.get("timestamp", True) else None,
    )
    if data.get("author"):
        embed.set_author(name=str(data["author"])[:256])
    if data.get("footer"):
        embed.set_footer(text=str(data["footer"])[:2048])
    for url_key in ("thumbnail_url", "image_url"):
        url = data.get(url_key)
        if url:
            if not valid_http_url(str(url)):
                raise ValueError(f"{url_key.replace('_', ' ').title()} must be an HTTP or HTTPS URL.")
            getattr(embed, "set_thumbnail" if url_key == "thumbnail_url" else "set_image")(url=str(url))
    fields = data.get("fields", [])
    for field in fields[:25]:
        embed.add_field(name=field["name"], value=field["value"], inline=False)
    if len(embed) > 6000:
        raise ValueError("The combined embed text must be 6,000 characters or fewer.")
    return embed


class EmbedBuilderCog(commands.Cog):
    embed = app_commands.Group(name="embed", description="Create, edit, preview, and send saved embeds.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get(self, interaction: discord.Interaction, name: str) -> dict | None:
        row = await self.bot.db.fetchone(
            "SELECT * FROM custom_embeds WHERE guild_id = ? AND owner_id = ? AND name = ?",
            (interaction.guild_id, interaction.user.id, name.strip().casefold()),
        )
        return dict(row) if row else None

    def _data(
        self,
        *,
        title: str,
        description: str,
        color: int,
        author: str | None,
        footer: str | None,
        thumbnail_url: str | None,
        image_url: str | None,
        fields: str | None,
        timestamp: bool,
    ) -> dict:
        if not 0 <= color <= 16777215:
            raise ValueError("Color must be between 0 and 16777215.")
        if not valid_http_url(thumbnail_url) or not valid_http_url(image_url):
            raise ValueError("Images must use valid HTTP or HTTPS URLs.")
        data = {
            "title": clean_text(title, 256),
            "description": clean_text(description, 4096, allow_empty=True),
            "color": color,
            "author": clean_text(author, 256) if author else None,
            "footer": clean_text(footer, 2048) if footer else None,
            "thumbnail_url": thumbnail_url.strip() if thumbnail_url else None,
            "image_url": image_url.strip() if image_url else None,
            "fields": parse_fields(fields),
            "timestamp": timestamp,
        }
        render_embed(data)
        return data

    @embed.command(name="create", description="Create a saved embed draft.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def create(
        self,
        interaction: discord.Interaction,
        name: app_commands.Range[str, 1, 50],
        title: app_commands.Range[str, 1, 256],
        description: app_commands.Range[str, 1, 4096],
        color: app_commands.Range[int, 0, 16777215] = 5793266,
        author: app_commands.Range[str, 1, 256] | None = None,
        footer: app_commands.Range[str, 1, 2048] | None = None,
        thumbnail_url: str | None = None,
        image_url: str | None = None,
        fields: str | None = None,
        timestamp: bool = True,
    ) -> None:
        try:
            data = self._data(
                title=title,
                description=description,
                color=color,
                author=author,
                footer=footer,
                thumbnail_url=thumbnail_url,
                image_url=image_url,
                fields=fields,
                timestamp=timestamp,
            )
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        try:
            await self.bot.db.execute(
                """INSERT INTO custom_embeds
                   (guild_id, owner_id, name, title, description, color, author, footer,
                    thumbnail_url, image_url, fields, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    interaction.guild_id, interaction.user.id, name.strip().casefold(),
                    data["title"], data["description"], data["color"], data["author"], data["footer"],
                    data["thumbnail_url"], data["image_url"], json.dumps(data["fields"]), int(timestamp),
                ),
            )
        except sqlite3.IntegrityError:
            await interaction.response.send_message(embed=error_embed("You already have an embed with that name."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=success_embed("Embed draft saved", f"Use `/embed preview name:{name}` to check it."),
            ephemeral=True,
        )

    @embed.command(name="edit", description="Update an embed draft you created.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def edit(
        self,
        interaction: discord.Interaction,
        name: app_commands.Range[str, 1, 50],
        title: app_commands.Range[str, 1, 256] | None = None,
        description: app_commands.Range[str, 1, 4096] | None = None,
        color: app_commands.Range[int, 0, 16777215] | None = None,
        author: app_commands.Range[str, 1, 256] | None = None,
        footer: app_commands.Range[str, 1, 2048] | None = None,
        thumbnail_url: str | None = None,
        image_url: str | None = None,
        fields: str | None = None,
        timestamp: bool | None = None,
    ) -> None:
        existing = await self._get(interaction, name)
        if not existing:
            await interaction.response.send_message(embed=error_embed("Embed draft not found. Create it first or check the name."), ephemeral=True)
            return
        try:
            next_data = {
                "title": title if title is not None else existing["title"],
                "description": description if description is not None else existing["description"],
                "color": color if color is not None else existing["color"],
                "author": author if author is not None else existing["author"],
                "footer": footer if footer is not None else existing["footer"],
                "thumbnail_url": thumbnail_url if thumbnail_url is not None else existing["thumbnail_url"],
                "image_url": image_url if image_url is not None else existing["image_url"],
                "fields": parse_fields(fields) if fields is not None else decode_json_list(existing["fields"]),
                "timestamp": bool(timestamp) if timestamp is not None else bool(existing["timestamp"]),
            }
            render_embed(next_data)
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        await self.bot.db.execute(
            """UPDATE custom_embeds SET title = ?, description = ?, color = ?, author = ?,
               footer = ?, thumbnail_url = ?, image_url = ?, fields = ?, timestamp = ?,
               updated_at = CURRENT_TIMESTAMP WHERE guild_id = ? AND owner_id = ? AND name = ?""",
            (
                next_data["title"], next_data["description"], next_data["color"], next_data["author"],
                next_data["footer"], next_data["thumbnail_url"], next_data["image_url"],
                json.dumps(next_data["fields"]), int(next_data["timestamp"]),
                interaction.guild_id, interaction.user.id, name.strip().casefold(),
            ),
        )
        await interaction.response.send_message(embed=success_embed("Embed updated", f"Saved changes to `{name}`."), ephemeral=True)

    @embed.command(name="preview", description="Preview one of your saved embeds privately.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def preview(self, interaction: discord.Interaction, name: str) -> None:
        data = await self._get(interaction, name)
        if not data:
            await interaction.response.send_message(embed=error_embed("Embed draft not found."), ephemeral=True)
            return
        try:
            embed = render_embed({
                **data,
                "fields": decode_json_list(data["fields"]),
                "timestamp": bool(data["timestamp"]),
            })
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @embed.command(name="send", description="Send a saved embed to a text channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def send(self, interaction: discord.Interaction, name: str, channel: discord.TextChannel) -> None:
        data = await self._get(interaction, name)
        if not data:
            await interaction.response.send_message(embed=error_embed("Embed draft not found."), ephemeral=True)
            return
        try:
            embed = render_embed({
                **data,
                "fields": decode_json_list(data["fields"]),
                "timestamp": bool(data["timestamp"]),
            })
            await channel.send(embed=embed)
        except (ValueError, discord.HTTPException) as exc:
            await interaction.response.send_message(embed=error_embed(f"Could not send this embed: {str(exc)[:250]}"), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Embed sent", f"Posted in {channel.mention}."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbedBuilderCog(bot))
