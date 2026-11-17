"""Centralized application-command error reporting."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from core.embed_builder import error_embed

logger = logging.getLogger("mybot")


async def handle_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.errors.MissingPermissions):
        message = "You do not have the Discord permissions required for this command."
    elif isinstance(error, app_commands.errors.CommandOnCooldown):
        message = f"Please wait {error.retry_after:.1f} seconds before using this command again."
    elif isinstance(error, app_commands.errors.NoPrivateMessage):
        message = "This command can only be used in a server."
    elif isinstance(error, app_commands.CommandInvokeError):
        logger.exception(
            "Slash command failed: %s",
            interaction.command.qualified_name if interaction.command else "unknown",
            exc_info=error.original,
        )
        message = "The command failed unexpectedly. The issue has been logged."
    else:
        logger.warning("Slash command error: %s", error, exc_info=error)
        message = "The command could not be completed. Check the inputs and try again."

    response = interaction.response
    if response.is_done():
        await interaction.followup.send(embed=error_embed(message), ephemeral=True)
    else:
        await response.send_message(embed=error_embed(message), ephemeral=True)
