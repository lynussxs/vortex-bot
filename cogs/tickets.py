"""Private ticket channels, staff actions, confirmation, and text transcripts."""

from __future__ import annotations

import io
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from core.embed_builder import error_embed, make_embed, success_embed


class TicketPanelView(discord.ui.View):
    def __init__(self, cog: "TicketsCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Open a ticket",
        style=discord.ButtonStyle.primary,
        custom_id="mybot:ticket:open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.create_ticket(interaction)


class TicketControlsView(discord.ui.View):
    def __init__(self, cog: "TicketsCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.secondary, custom_id="mybot:ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.claim_ticket(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="mybot:ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.confirm_close(interaction)


class TicketCloseConfirm(discord.ui.View):
    def __init__(self, cog: "TicketsCog", requester_id: int, channel_id: int) -> None:
        super().__init__(timeout=45)
        self.cog = cog
        self.requester_id = requester_id
        self.channel_id = channel_id

    @discord.ui.button(label="Confirm close", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the person who started closing this ticket can confirm.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog.close_ticket(interaction, self.channel_id)
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=success_embed("Ticket closed", "The channel is now read-only."), view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the person who started closing this ticket can cancel.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=make_embed("Ticket remains open"), view=self)
        self.stop()


class TicketsCog(commands.Cog):
    ticket = app_commands.Group(name="ticket", description="Configure and manage private support tickets.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketControlsView(self))
        rows = await self.bot.db.fetchall(
            "SELECT guild_id, panel_channel_id, panel_message_id FROM ticket_settings WHERE panel_message_id IS NOT NULL",
        )
        for row in rows:
            self.bot.add_view(
                TicketPanelView(self),
                message_id=row["panel_message_id"],
            )

    @ticket.command(name="setup", description="Create or update the ticket panel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup_panel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        staff_role: discord.Role | None = None,
        category: discord.CategoryChannel | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        if not guild.me or not guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=error_embed("MyBot needs Manage Channels permission to create ticket panels."), ephemeral=True)
            return
        await self._publish_panel(guild, channel, staff_role, category)
        await interaction.response.send_message(embed=success_embed("Ticket panel ready", f"Panel posted in {channel.mention}."), ephemeral=True)

    async def _publish_panel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        staff_role: discord.Role | None,
        category: discord.CategoryChannel | None,
    ) -> discord.Message:
        row = await self.bot.db.fetchone(
            "SELECT panel_message_id, panel_channel_id, category_id, staff_role_id FROM ticket_settings WHERE guild_id = ?",
            (guild.id,),
        )
        if row:
            if category is None and row["category_id"]:
                candidate = guild.get_channel(row["category_id"])
                category = candidate if isinstance(candidate, discord.CategoryChannel) else None
            if staff_role is None and row["staff_role_id"]:
                staff_role = guild.get_role(row["staff_role_id"])
        panel_message = None
        if row and row["panel_message_id"] and row["panel_channel_id"] == channel.id:
            try:
                panel_message = await channel.fetch_message(row["panel_message_id"])
            except discord.HTTPException:
                panel_message = None
        view = TicketPanelView(self)
        embed = make_embed("Need help?", "Open a private ticket and a staff member will assist you.")
        if panel_message:
            await panel_message.edit(embed=embed, view=view)
        else:
            panel_message = await channel.send(embed=embed, view=view)
        await self.bot.db.execute(
            """INSERT INTO ticket_settings(guild_id, panel_channel_id, panel_message_id, category_id, staff_role_id)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET panel_channel_id = excluded.panel_channel_id,
                   panel_message_id = excluded.panel_message_id, category_id = excluded.category_id,
                   staff_role_id = excluded.staff_role_id""",
            (guild.id, channel.id, panel_message.id, category.id if category else None, staff_role.id if staff_role else None),
        )
        self.bot.add_view(view, message_id=panel_message.id)
        return panel_message

    @ticket.command(name="panel", description="Post a new ticket panel in a channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def panel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if interaction.guild is None:
            return
        if not interaction.guild.me or not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=error_embed("MyBot needs Manage Channels permission to create ticket panels."), ephemeral=True)
            return
        await self._publish_panel(interaction.guild, channel, None, None)
        await interaction.response.send_message(embed=success_embed("Ticket panel ready", f"Panel posted in {channel.mention}."), ephemeral=True)

    async def create_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Tickets can only be opened in a server.", ephemeral=True)
            return
        existing = await self.bot.db.fetchone(
            "SELECT channel_id FROM tickets WHERE guild_id = ? AND opener_id = ? AND status = 'open'",
            (guild.id, interaction.user.id),
        )
        if existing:
            channel = guild.get_channel(existing["channel_id"])
            await interaction.response.send_message(
                f"You already have an open ticket: {channel.mention if channel else 'the channel is unavailable'}.",
                ephemeral=True,
            )
            return
        settings = await self.bot.db.fetchone("SELECT category_id, staff_role_id FROM ticket_settings WHERE guild_id = ?", (guild.id,))
        if not settings:
            await interaction.response.send_message(embed=error_embed("Ticket setup is incomplete. Ask a server administrator."), ephemeral=True)
            return
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)
        staff_role = guild.get_role(settings["staff_role_id"]) if settings["staff_role_id"] else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        category = guild.get_channel(settings["category_id"]) if settings["category_id"] else None
        if not isinstance(category, discord.CategoryChannel):
            category = None
        safe_name = "".join(char.lower() if char.isalnum() else "-" for char in interaction.user.display_name).strip("-")[:30] or "member"
        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{safe_name}",
                category=category,
                overwrites=overwrites,
                reason=f"Ticket opened by {interaction.user}",
            )
        except discord.HTTPException:
            await interaction.response.send_message(embed=error_embed("MyBot could not create the private ticket channel."), ephemeral=True)
            return
        try:
            await self.bot.db.execute(
                "INSERT INTO tickets(guild_id, channel_id, opener_id) VALUES (?, ?, ?)",
                (guild.id, channel.id, interaction.user.id),
            )
        except sqlite3.IntegrityError:
            await channel.delete(reason="Concurrent duplicate ticket request")
            existing = await self.bot.db.fetchone(
                "SELECT channel_id FROM tickets WHERE guild_id = ? AND opener_id = ? AND status = 'open'",
                (guild.id, interaction.user.id),
            )
            existing_channel = guild.get_channel(existing["channel_id"]) if existing else None
            await interaction.response.send_message(
                f"You already have an open ticket: {existing_channel.mention if existing_channel else 'check with staff'}.",
                ephemeral=True,
            )
            return
        await channel.send(
            f"{interaction.user.mention} opened a ticket. Staff will reply here.",
            embed=make_embed("Support ticket", "Share the details needed to help you. Do not post passwords or other secrets."),
            view=TicketControlsView(self),
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await interaction.response.send_message(f"Your ticket is ready: {channel.mention}", ephemeral=True)

    async def _ticket_row(self, channel_id: int) -> dict | None:
        row = await self.bot.db.fetchone(
            "SELECT * FROM tickets WHERE channel_id = ? AND status = 'open'",
            (channel_id,),
        )
        return dict(row) if row else None

    async def _is_staff(self, member: discord.Member, guild_id: int) -> bool:
        if member.guild_permissions.manage_channels or member.guild_permissions.administrator:
            return True
        settings = await self.bot.db.fetchone("SELECT staff_role_id FROM ticket_settings WHERE guild_id = ?", (guild_id,))
        role_id = settings["staff_role_id"] if settings else None
        return bool(role_id and any(role.id == role_id for role in member.roles))

    async def confirm_close(self, interaction: discord.Interaction) -> None:
        row = await self._ticket_row(interaction.channel_id)
        if row is None:
            await interaction.response.send_message(embed=error_embed("This is not an open ticket."), ephemeral=True)
            return
        staff = isinstance(interaction.user, discord.Member) and await self._is_staff(interaction.user, interaction.guild_id)
        if interaction.user.id != row["opener_id"] and not staff:
            await interaction.response.send_message(embed=error_embed("Only the ticket owner or staff can close this ticket."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=make_embed("Close this ticket?", "MyBot will save a text transcript and make this channel read-only."),
            view=TicketCloseConfirm(self, interaction.user.id, interaction.channel_id),
            ephemeral=True,
        )

    async def close_ticket(self, interaction: discord.Interaction, channel_id: int) -> None:
        row = await self._ticket_row(channel_id)
        channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
        if row is None or not isinstance(channel, discord.TextChannel):
            return
        transcript_lines = []
        async for message in channel.history(limit=1000, oldest_first=True):
            content = message.clean_content.replace("\n", " ")
            transcript_lines.append(f"[{message.created_at.isoformat()}] {message.author}: {content[:1500]}")
        transcript = "\n".join(transcript_lines).encode("utf-8") or b"No messages."
        await channel.send(file=discord.File(io.BytesIO(transcript), filename=f"ticket-{row['id']}-transcript.txt"))
        opener = interaction.guild.get_member(row["opener_id"])
        if opener:
            await channel.set_permissions(opener, send_messages=False, reason="Ticket closed")
        await self.bot.db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE channel_id = ?",
            (channel_id,),
        )
        await channel.edit(name=f"closed-{channel.name}"[:100], reason=f"Ticket closed by {interaction.user}")

    async def claim_ticket(self, interaction: discord.Interaction) -> None:
        row = await self._ticket_row(interaction.channel_id)
        if row is None:
            await interaction.response.send_message(embed=error_embed("This is not an open ticket."), ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not await self._is_staff(interaction.user, interaction.guild_id):
            await interaction.response.send_message(embed=error_embed("Only ticket staff can claim tickets."), ephemeral=True)
            return
        if row["claimed_by"]:
            await interaction.response.send_message(embed=error_embed(f"This ticket is already claimed by <@{row['claimed_by']}>."), ephemeral=True)
            return
        await self.bot.db.execute("UPDATE tickets SET claimed_by = ? WHERE channel_id = ?", (interaction.user.id, interaction.channel_id))
        await interaction.response.send_message(embed=success_embed("Ticket claimed", f"{interaction.user.mention} is handling this ticket."))

    @ticket.command(name="close", description="Close the current ticket with a transcript.")
    @app_commands.guild_only()
    async def close_command(self, interaction: discord.Interaction) -> None:
        await self.confirm_close(interaction)

    @ticket.command(name="claim", description="Claim the current ticket for staff follow-up.")
    @app_commands.guild_only()
    async def claim_command(self, interaction: discord.Interaction) -> None:
        await self.claim_ticket(interaction)

    @ticket.command(name="add", description="Give a member access to the current ticket.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def add_member(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not isinstance(interaction.channel, discord.TextChannel) or not await self._ticket_row(interaction.channel_id):
            await interaction.response.send_message(embed=error_embed("Use this command inside an open ticket."), ephemeral=True)
            return
        await interaction.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(embed=success_embed("Member added", f"{member.mention} can now view this ticket."), ephemeral=True)

    @ticket.command(name="remove", description="Remove a member's access to the current ticket.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def remove_member(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not isinstance(interaction.channel, discord.TextChannel) or not await self._ticket_row(interaction.channel_id):
            await interaction.response.send_message(embed=error_embed("Use this command inside an open ticket."), ephemeral=True)
            return
        await interaction.channel.set_permissions(member, overwrite=None, reason=f"Removed by {interaction.user}")
        await interaction.response.send_message(embed=success_embed("Member removed", f"{member.mention} can no longer view this ticket."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
