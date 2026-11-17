"""Permission and role-hierarchy checks shared by moderation features."""

from __future__ import annotations

import discord

PROTECTED_PERMISSIONS = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_messages",
    "view_audit_log",
    "ban_members",
    "kick_members",
    "moderate_members",
    "manage_webhooks",
    "manage_events",
    "manage_nicknames",
)


def can_moderate(
    moderator: discord.Member,
    target: discord.Member,
    bot_member: discord.Member | None,
) -> tuple[bool, str]:
    if moderator.id == target.id:
        return False, "You cannot target yourself."
    if target.bot and bot_member is not None and target.id == bot_member.id:
        return False, "You cannot target Vortex."
    if moderator.guild.owner_id != moderator.id and target.top_role >= moderator.top_role:
        return False, "That member has an equal or higher role than yours."
    if bot_member is None or target.top_role >= bot_member.top_role:
        return False, "Vortex's highest role must be above the target's highest role."
    return True, ""


def is_protected_role(role: discord.Role) -> bool:
    return any(getattr(role.permissions, permission, False) for permission in PROTECTED_PERMISSIONS)


def bot_can_manage_role(guild: discord.Guild, role: discord.Role) -> bool:
    me = guild.me
    return bool(me and me.guild_permissions.manage_roles and role < me.top_role and not role.is_default())
