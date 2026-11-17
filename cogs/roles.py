"""Role administration and restart-persistent self-assignable role panels."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, make_embed, success_embed
from core.permissions import bot_can_manage_role, is_protected_role


class RoleToggleButton(discord.ui.Button["RolePanelView"]):
    def __init__(self, record: dict) -> None:
        self.record_id = int(record["id"])
        self.role_id = int(record["role_id"])
        super().__init__(
            label=str(record["label"])[:80],
            custom_id=f"mybot:role:{self.record_id}",
            style=discord.ButtonStyle(int(record.get("style", 1))),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = self.view.cog
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use this panel in its server.", ephemeral=True)
            return
        record = await cog.bot.db.fetchone(
            "SELECT role_id FROM reaction_roles WHERE id = ? AND guild_id = ?",
            (self.record_id, guild.id),
        )
        role = guild.get_role(record["role_id"]) if record else None
        if role is None or is_protected_role(role) or not bot_can_manage_role(guild, role):
            await interaction.response.send_message(embed=error_embed("This role is no longer available."), ephemeral=True)
            return
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Self-assignable role panel")
                message = f"Removed {role.mention}."
            else:
                await interaction.user.add_roles(role, reason="Self-assignable role panel")
                message = f"Added {role.mention}."
        except discord.Forbidden:
            await interaction.response.send_message(embed=error_embed("Vortex cannot manage that role."), ephemeral=True)
            return
        await interaction.response.send_message(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class RoleMenuSelect(discord.ui.Select["RoleMenuView"]):
    def __init__(self, message_id: int, records: list[dict]) -> None:
        options = [
            discord.SelectOption(label=str(row["label"])[:100], value=str(row["role_id"]))
            for row in records[:25]
        ]
        super().__init__(
            custom_id=f"mybot:role-menu:{message_id}",
            placeholder="Choose roles to toggle",
            min_values=1,
            max_values=max(1, len(options)),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use this menu in its server.", ephemeral=True)
            return
        added: list[str] = []
        removed: list[str] = []
        for value in self.values:
            try:
                role_id = int(value)
            except ValueError:
                continue
            role = guild.get_role(role_id)
            if not role or is_protected_role(role) or not bot_can_manage_role(guild, role):
                continue
            try:
                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role, reason="Self-assignable role menu")
                    removed.append(role.name)
                else:
                    await interaction.user.add_roles(role, reason="Self-assignable role menu")
                    added.append(role.name)
            except discord.HTTPException:
                continue
        parts = []
        if added:
            parts.append("Added: " + ", ".join(added[:10]))
        if removed:
            parts.append("Removed: " + ", ".join(removed[:10]))
        await interaction.response.send_message(
            "\n".join(parts) if parts else "No roles could be changed.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class RolePanelView(discord.ui.View):
    def __init__(self, cog: "RolesCog", records: list[dict]) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        for record in records[:25]:
            self.add_item(RoleToggleButton(record))


class RoleMenuView(discord.ui.View):
    def __init__(self, message_id: int, records: list[dict]) -> None:
        super().__init__(timeout=None)
        if records:
            self.add_item(RoleMenuSelect(message_id, records))


class RolesCog(commands.Cog):
    role = app_commands.Group(name="role", description="Manage server roles.")
    reactionrole = app_commands.Group(name="reactionrole", description="Create self-assignable role panels.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM reaction_roles ORDER BY message_id, id",
        )
        by_message: dict[int, list[dict]] = {}
        for row in rows:
            by_message.setdefault(int(row["message_id"]), []).append(dict(row))
        for message_id, records in by_message.items():
            if records[0].get("panel_type") == "menu":
                self.bot.add_view(RoleMenuView(message_id, records), message_id=message_id)
            else:
                self.bot.add_view(RolePanelView(self, records), message_id=message_id)

    @role.command(name="add", description="Assign a role to a member.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role) -> None:
        if not self._can_assign(interaction, role):
            await interaction.response.send_message(embed=error_embed("Vortex or your role is not high enough, or the role is protected."), ephemeral=True)
            return
        if member.top_role >= role and interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message(embed=error_embed("You cannot assign a role at or above the member's highest role."), ephemeral=True)
            return
        try:
            await member.add_roles(role, reason=f"Role assigned by {interaction.user}")
        except discord.HTTPException:
            await interaction.response.send_message(embed=error_embed("Discord could not assign that role."), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Role assigned", f"{role.mention} was added to {member.mention}."), ephemeral=True)

    @role.command(name="remove", description="Remove a role from a member.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role) -> None:
        if not self._can_assign(interaction, role):
            await interaction.response.send_message(embed=error_embed("Vortex or your role is not high enough, or the role is protected."), ephemeral=True)
            return
        try:
            await member.remove_roles(role, reason=f"Role removed by {interaction.user}")
        except discord.HTTPException:
            await interaction.response.send_message(embed=error_embed("Discord could not remove that role."), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Role removed", f"{role.mention} was removed from {member.mention}."), ephemeral=True)

    @role.command(name="create", description="Create a basic role without administrative permissions.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def role_create(
        self,
        interaction: discord.Interaction,
        name: app_commands.Range[str, 1, 100],
        color: app_commands.Range[int, 0, 16777215] = 5793266,
    ) -> None:
        if not interaction.guild.me or not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message(embed=error_embed("Vortex needs Manage Roles permission."), ephemeral=True)
            return
        try:
            role = await interaction.guild.create_role(
                name=name,
                colour=discord.Colour(color),
                permissions=discord.Permissions.none(),
                reason=f"Created by {interaction.user}",
            )
        except discord.HTTPException:
            await interaction.response.send_message(embed=error_embed("Discord could not create that role."), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Role created", f"Created {role.mention}."), ephemeral=True)

    @role.command(name="delete", description="Delete a role.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def role_delete(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not self._can_assign(interaction, role):
            await interaction.response.send_message(embed=error_embed("Vortex or your role is not high enough, or the role is protected."), ephemeral=True)
            return
        role_name = role.name
        try:
            await role.delete(reason=f"Deleted by {interaction.user}")
        except discord.HTTPException:
            await interaction.response.send_message(embed=error_embed("Discord could not delete that role."), ephemeral=True)
            return
        await interaction.response.send_message(embed=success_embed("Role deleted", f"`{role_name}` was deleted."), ephemeral=True)

    def _can_assign(self, interaction: discord.Interaction, role: discord.Role) -> bool:
        guild = interaction.guild
        member = interaction.user
        return bool(
            guild
            and isinstance(member, discord.Member)
            and not role.is_default()
            and not is_protected_role(role)
            and bot_can_manage_role(guild, role)
            and (guild.owner_id == member.id or role < member.top_role)
        )

    @reactionrole.command(name="create", description="Add a role button to a new or existing role panel.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def reactionrole_create(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        label: app_commands.Range[str, 1, 80] | None = None,
        channel: discord.TextChannel | None = None,
        panel_message_id: str | None = None,
    ) -> None:
        guild = interaction.guild
        channel = channel or interaction.channel
        if not guild or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Choose a text channel for the panel."), ephemeral=True)
            return
        if not self._can_assign(interaction, role):
            await interaction.response.send_message(embed=error_embed("That role is protected or not manageable."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        message = None
        if panel_message_id:
            try:
                message = await channel.fetch_message(int(panel_message_id))
            except (ValueError, discord.HTTPException):
                await interaction.followup.send(embed=error_embed("Could not find that panel message in the selected channel."), ephemeral=True)
                return
            if message.author.id != self.bot.user.id:
                await interaction.followup.send(embed=error_embed("Only Vortex-created messages can be role panels."), ephemeral=True)
                return
            current_rows = await self.bot.db.fetchall(
                "SELECT * FROM reaction_roles WHERE message_id = ?",
                (message.id,),
            )
            if len(current_rows) >= 25:
                await interaction.followup.send(embed=error_embed("A role button panel can contain at most 25 roles."), ephemeral=True)
                return
            if current_rows and current_rows[0]["panel_type"] != "button":
                await interaction.followup.send(embed=error_embed("Button roles cannot be added to a select-menu panel."), ephemeral=True)
                return
            if any(row["role_id"] == role.id for row in current_rows):
                await interaction.followup.send(embed=error_embed("That role is already on this panel."), ephemeral=True)
                return
        else:
            panel_embed = make_embed("Choose a role", "Use a button below to add or remove the role.")
            message = await channel.send(embed=panel_embed)
            current_rows = []
        record_id = await self.bot.db.execute(
            """INSERT INTO reaction_roles(guild_id, channel_id, message_id, role_id, label, style)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (guild.id, channel.id, message.id, role.id, label or role.name),
        )
        rows = [dict(row) for row in current_rows] + [{
            "id": record_id,
            "guild_id": guild.id,
            "channel_id": channel.id,
            "message_id": message.id,
            "role_id": role.id,
            "label": label or role.name,
            "style": 1,
            "panel_type": "button",
        }]
        view = RolePanelView(self, rows)
        await message.edit(view=view)
        self.bot.add_view(view, message_id=message.id)
        await interaction.followup.send(embed=success_embed("Role panel updated", f"Added a button for {role.mention} in {channel.mention}."), ephemeral=True)

    @reactionrole.command(name="select", description="Create a select-menu role panel.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def reactionrole_select(
        self,
        interaction: discord.Interaction,
        roles: app_commands.Range[str, 1, 500],
        channel: discord.TextChannel | None = None,
    ) -> None:
        guild = interaction.guild
        channel = channel or interaction.channel
        if not guild or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Choose a text channel for the panel."), ephemeral=True)
            return
        role_ids = []
        for token in roles.replace("<@&", "").replace(">", "").replace(",", " ").split():
            try:
                role_ids.append(int(token))
            except ValueError:
                continue
        role_ids = list(dict.fromkeys(role_ids))[:25]
        valid_roles = [guild.get_role(role_id) for role_id in role_ids]
        valid_roles = [role for role in valid_roles if role and self._can_assign(interaction, role)]
        if not valid_roles:
            await interaction.response.send_message(embed=error_embed("Provide up to 25 manageable role mentions or IDs."), ephemeral=True)
            return
        embed = make_embed("Choose roles", "Select roles to toggle on or off.")
        embed.set_footer(text="mybot-role-menu")
        message = await channel.send(embed=embed)
        records = []
        for role in valid_roles:
            record_id = await self.bot.db.execute(
                """INSERT INTO reaction_roles(guild_id, channel_id, message_id, role_id, label)
                   VALUES (?, ?, ?, ?, ?)""",
                (guild.id, channel.id, message.id, role.id, role.name),
            )
            records.append({
                "id": record_id, "guild_id": guild.id, "channel_id": channel.id,
                "message_id": message.id, "role_id": role.id, "label": role.name,
                "panel_type": "menu",
            })
            await self.bot.db.execute(
                "UPDATE reaction_roles SET panel_type = 'menu' WHERE id = ?",
                (record_id,),
            )
        view = RoleMenuView(message.id, records)
        await message.edit(view=view)
        self.bot.add_view(view, message_id=message.id)
        await interaction.response.send_message(embed=success_embed("Select menu created", f"Added {len(records)} role(s) in {channel.mention}."), ephemeral=True)

    @reactionrole.command(name="remove", description="Remove a role from a role panel.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def reactionrole_remove(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        panel_message_id: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        channel = channel or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Choose the panel's text channel."), ephemeral=True)
            return
        try:
            message_id = int(panel_message_id)
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Panel message ID must be numeric."), ephemeral=True)
            return
        existing = await self.bot.db.fetchone(
            "SELECT panel_type FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND role_id = ?",
            (interaction.guild_id, message_id, role.id),
        )
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND role_id = ?",
            (interaction.guild_id, message_id, role.id),
        )
        rows = await self.bot.db.fetchall("SELECT * FROM reaction_roles WHERE message_id = ?", (message_id,))
        try:
            message = await channel.fetch_message(message_id)
            if rows:
                records = [dict(row) for row in rows]
                is_menu = bool((existing and existing["panel_type"] == "menu") or records[0].get("panel_type") == "menu")
                await message.edit(view=RoleMenuView(message_id, records) if is_menu else RolePanelView(self, records))
            else:
                await message.edit(view=None)
        except discord.HTTPException:
            pass
        await interaction.response.send_message(embed=success_embed("Panel updated", f"Removed {role.mention} from the panel."), ephemeral=True)

    @reactionrole.command(name="list", description="List self-assignable roles for this server.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def reactionrole_list(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT message_id, role_id, label FROM reaction_roles WHERE guild_id = ? ORDER BY message_id, id",
            (interaction.guild_id,),
        )
        embed = make_embed("Self-assignable roles")
        if rows:
            embed.description = "\n".join(
                f"Panel `{row['message_id']}` · <@&{row['role_id']}> · {row['label']}"
                for row in rows[:25]
            )
        else:
            embed.description = "No role panels are configured."
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RolesCog(bot))
