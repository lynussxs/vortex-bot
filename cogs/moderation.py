"""Kiem duyet (nhu ProBot): ban/kick/timeout/warn/purge/lock... Moi hanh dong ghi case + log."""
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.cases import record_case
from core.util import C_ERR, C_INFO, C_OK, C_WARN, NO_MENTIONS, fmt_duration, hierarchy_error, parse_duration

MAX_TIMEOUT = timedelta(days=28)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _guard(self, interaction, target: discord.Member) -> bool:
        err = hierarchy_error(interaction.guild, interaction.user, target)
        if err:
            await interaction.response.send_message(f"❌ {err}", ephemeral=True)
            return False
        return True

    async def _dm(self, user, title: str, reason: str, guild: discord.Guild):
        try:
            await user.send(embed=discord.Embed(
                title=title, description=f"Server: **{guild.name}**\nLý do: {reason}", color=C_WARN))
        except discord.HTTPException:
            pass

    @staticmethod
    def _done(text: str, color=C_OK) -> discord.Embed:
        return discord.Embed(description=text, color=color)

    # ------------------------------------------------------------------ ban / kick
    @app_commands.command(name="ban", description="Cấm một thành viên khỏi server")
    @app_commands.describe(user="Người cần ban", reason="Lý do", delete_days="Xóa tin nhắn trong N ngày gần đây (0-7)")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, user: discord.User, reason: str = "Không có lý do",
                  delete_days: app_commands.Range[int, 0, 7] = 0):
        member = interaction.guild.get_member(user.id)
        if member and not await self._guard(interaction, member):
            return
        await interaction.response.defer()
        await self._dm(user, "🔨 Bạn đã bị ban", reason, interaction.guild)
        try:
            await interaction.guild.ban(user, reason=f"{interaction.user}: {reason}"[:500],
                                        delete_message_seconds=delete_days * 86400)
        except discord.Forbidden:
            return await interaction.followup.send("❌ Bot thiếu quyền Ban Members hoặc role thấp hơn.")
        cid = await record_case(self.bot, interaction.guild, "Ban", user, interaction.user, reason, color=C_ERR)
        await interaction.followup.send(embed=self._done(f"🔨 Đã ban **{user}** · Case #{cid}"))

    @app_commands.command(name="unban", description="Gỡ ban theo ID người dùng")
    @app_commands.describe(user_id="ID của người bị ban", reason="Lý do")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Không có lý do"):
        if not user_id.isdigit():
            return await interaction.response.send_message("❌ ID không hợp lệ.", ephemeral=True)
        await interaction.response.defer()
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}"[:500])
        except discord.NotFound:
            return await interaction.followup.send("❌ Không tìm thấy người này trong danh sách ban.")
        except discord.Forbidden:
            return await interaction.followup.send("❌ Bot thiếu quyền Ban Members.")
        cid = await record_case(self.bot, interaction.guild, "Unban", user, interaction.user, reason,
                                public=False, color=C_OK)
        await interaction.followup.send(embed=self._done(f"✅ Đã gỡ ban **{user}** · Case #{cid}"))

    @app_commands.command(name="kick", description="Đuổi một thành viên khỏi server")
    @app_commands.describe(member="Người cần kick", reason="Lý do")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Không có lý do"):
        if not await self._guard(interaction, member):
            return
        await interaction.response.defer()
        await self._dm(member, "👢 Bạn đã bị kick", reason, interaction.guild)
        try:
            await member.kick(reason=f"{interaction.user}: {reason}"[:500])
        except discord.Forbidden:
            return await interaction.followup.send("❌ Bot thiếu quyền Kick Members hoặc role thấp hơn.")
        cid = await record_case(self.bot, interaction.guild, "Kick", member, interaction.user, reason)
        await interaction.followup.send(embed=self._done(f"👢 Đã kick **{member}** · Case #{cid}"))

    # ------------------------------------------------------------------ timeout
    @app_commands.command(name="timeout", description="Cấm chat tạm thời (mute)")
    @app_commands.describe(member="Người cần timeout", duration="Thời gian: 10m, 2h, 1d (tối đa 28d)", reason="Lý do")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: str,
                      reason: str = "Không có lý do"):
        td = parse_duration(duration)
        if not td or td > MAX_TIMEOUT:
            return await interaction.response.send_message(
                "❌ Thời gian không hợp lệ. Ví dụ: `10m`, `2h`, `1d` (tối đa 28d).", ephemeral=True)
        if not await self._guard(interaction, member):
            return
        await interaction.response.defer()
        try:
            await member.timeout(td, reason=f"{interaction.user}: {reason}"[:500])
        except discord.Forbidden:
            return await interaction.followup.send("❌ Bot thiếu quyền Moderate Members hoặc role thấp hơn.")
        await self._dm(member, "🔇 Bạn bị timeout", f"{reason} (trong {fmt_duration(td)})", interaction.guild)
        cid = await record_case(self.bot, interaction.guild, "Timeout", member, interaction.user, reason,
                                {"Thời hạn": fmt_duration(td)})
        await interaction.followup.send(embed=self._done(f"🔇 **{member}** bị timeout {fmt_duration(td)} · Case #{cid}"))

    @app_commands.command(name="untimeout", description="Gỡ timeout")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        try:
            await member.timeout(None, reason=f"{interaction.user}: gỡ timeout")
        except discord.Forbidden:
            return await interaction.followup.send("❌ Bot thiếu quyền hoặc role thấp hơn.")
        await interaction.followup.send(embed=self._done(f"🔊 Đã gỡ timeout cho **{member}**"))

    # ------------------------------------------------------------------ warn
    @app_commands.command(name="warn", description="Cảnh cáo một thành viên")
    @app_commands.describe(member="Người bị cảnh cáo", reason="Lý do")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await self._guard(interaction, member):
            return
        await interaction.response.defer()
        g, db = interaction.guild, self.bot.db
        cid = await record_case(self.bot, g, "Warn", member, interaction.user, reason)
        count = await db.count_cases(g.id, member.id, "Warn")
        await self._dm(member, f"⚠️ Bạn bị cảnh cáo (lần {count})", reason, g)
        note = ""
        threshold = await db.get_int(g.id, "warn_threshold", 3)
        if threshold and count % threshold == 0:
            minutes = await db.get_int(g.id, "warn_timeout_min", 60)
            try:
                await member.timeout(timedelta(minutes=minutes), reason=f"Đủ {count} cảnh cáo")
                await record_case(self.bot, g, "Timeout", member, self.bot.user, f"Tự động: đủ {count} cảnh cáo",
                                  {"Thời hạn": f"{minutes}m"})
                note = f"\n🔇 Đủ {count} cảnh cáo → tự động timeout {minutes} phút."
            except discord.HTTPException:
                note = "\n⚠️ Đủ ngưỡng cảnh cáo nhưng bot không timeout được (thiếu quyền?)."
        await interaction.followup.send(embed=self._done(f"⚠️ Đã cảnh cáo **{member}** (lần {count}) · Case #{cid}{note}"))

    @app_commands.command(name="warnings", description="Xem lịch sử cảnh cáo")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warnings(self, interaction: discord.Interaction, user: discord.User):
        rows = await self.bot.db.user_cases(interaction.guild_id, user.id, limit=10)
        if not rows:
            return await interaction.response.send_message(f"✅ **{user}** chưa có case nào.", ephemeral=True)
        lines = [f"`#{r['id']}` **{r['action']}** · <t:{r['created_at']}:d> · {r['reason'][:80]}" for r in rows]
        e = discord.Embed(title=f"📋 Lịch sử của {user}", description="\n".join(lines), color=C_INFO)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="clearwarns", description="Xóa toàn bộ cảnh cáo của một người")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def clearwarns(self, interaction: discord.Interaction, user: discord.User):
        n = await self.bot.db.clear_cases(interaction.guild_id, user.id, "Warn")
        await interaction.response.send_message(f"🧹 Đã xóa {n} cảnh cáo của **{user}**.", ephemeral=True)

    # ------------------------------------------------------------------ kenh
    @app_commands.command(name="purge", description="Xóa nhiều tin nhắn")
    @app_commands.describe(amount="Số tin cần quét (1-100)", member="Chỉ xóa tin của người này")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100],
                    member: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        check = (lambda m: m.author.id == member.id) if member else None
        try:
            deleted = await interaction.channel.purge(limit=amount, check=check)
        except discord.Forbidden:
            return await interaction.followup.send("❌ Bot thiếu quyền Manage Messages ở kênh này.")
        await interaction.followup.send(f"🧹 Đã xóa {len(deleted)} tin nhắn.")

    @app_commands.command(name="slowmode", description="Đặt chế độ chậm cho kênh")
    @app_commands.describe(seconds="Số giây giữa hai tin nhắn (0 để tắt)", channel="Kênh (mặc định kênh hiện tại)")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600],
                       channel: Optional[discord.TextChannel] = None):
        channel = channel or interaction.channel
        try:
            await channel.edit(slowmode_delay=seconds, reason=f"{interaction.user}: slowmode")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Bot thiếu quyền Manage Channels.", ephemeral=True)
        await interaction.response.send_message(f"🐢 Slowmode của {channel.mention}: **{seconds}s**")

    async def _set_lock(self, interaction, channel, locked: bool):
        channel = channel or interaction.channel
        everyone = interaction.guild.default_role
        ow = channel.overwrites_for(everyone)
        ow.send_messages = False if locked else None
        try:
            await channel.set_permissions(everyone, overwrite=ow, reason=f"{interaction.user}: {'lock' if locked else 'unlock'}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Bot thiếu quyền Manage Channels.", ephemeral=True)
        await interaction.response.send_message(
            f"{'🔒 Đã khóa' if locked else '🔓 Đã mở khóa'} {channel.mention}", allowed_mentions=NO_MENTIONS)

    @app_commands.command(name="lock", description="Khóa kênh, không cho @everyone gửi tin")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def lock(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await self._set_lock(interaction, channel, True)

    @app_commands.command(name="unlock", description="Mở khóa kênh")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def unlock(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await self._set_lock(interaction, channel, False)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
