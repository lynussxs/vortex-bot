"""Reusable application-command checks."""

from __future__ import annotations

import discord
from discord import app_commands


def guild_only() -> app_commands.Check:
    return app_commands.checks.guild_only()


def require_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.guild and isinstance(interaction.user, discord.Member)
                and interaction.user.guild_permissions.administrator)


def is_owner(interaction: discord.Interaction, owner_id: int | None) -> bool:
    return owner_id is not None and interaction.user.id == owner_id
