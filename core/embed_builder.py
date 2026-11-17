"""Consistent, branded embeds for command responses and logs."""

from __future__ import annotations

import discord

BRAND_COLOR = discord.Color.from_rgb(88, 101, 242)
SUCCESS_COLOR = discord.Color.from_rgb(46, 204, 113)
WARNING_COLOR = discord.Color.from_rgb(241, 196, 15)
ERROR_COLOR = discord.Color.from_rgb(231, 76, 60)
GOLD_COLOR = discord.Color.from_rgb(255, 193, 7)

# Updated at startup with the bot's real name / avatar (see MyBot.on_ready).
BRAND_NAME = "MyBot"
BRAND_ICON_URL: str | None = None


def set_branding(name: str, icon_url: str | None) -> None:
    global BRAND_NAME, BRAND_ICON_URL
    BRAND_NAME, BRAND_ICON_URL = name, icon_url


def make_embed(
    title: str,
    description: str | None = None,
    *,
    color: discord.Color = BRAND_COLOR,
    footer: bool = True,
) -> discord.Embed:
    embed = discord.Embed(title=title[:256], description=(description or "")[:4096], color=color)
    embed.timestamp = discord.utils.utcnow()
    if footer:
        embed.set_footer(text=BRAND_NAME, icon_url=BRAND_ICON_URL)
    return embed


def success_embed(title: str, description: str) -> discord.Embed:
    return make_embed(f"✅ {title}", description, color=SUCCESS_COLOR)


def warning_embed(title: str, description: str) -> discord.Embed:
    return make_embed(f"⚠️ {title}", description, color=WARNING_COLOR)


def error_embed(description: str, title: str = "Something went wrong") -> discord.Embed:
    return make_embed(f"❌ {title}", description, color=ERROR_COLOR)
