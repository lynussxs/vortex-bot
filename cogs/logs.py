"""Nhat ky server: tin nhan, thanh vien, role, kenh, voice -> kenh log-server."""
import discord
from discord.ext import commands

from core.util import C_ERR, C_INFO, C_OK, C_WARN, send_log, utcnow


class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _log(self, guild, title, color, desc=None, **fields):
        e = discord.Embed(title=title, description=desc, color=color, timestamp=utcnow())
        for k, v in fields.items():
            if v:
                e.add_field(name=k.replace("_", " "), value=str(v)[:1000], inline=False)
        await send_log(self.bot, guild, "ch_log", e)

    async def _is_log_channel(self, channel) -> bool:
        return bool(channel and channel.guild and channel.id in {
            await self.bot.db.get_int(channel.guild.id, "ch_log") or 0,
            await self.bot.db.get_int(channel.guild.id, "ch_modlog") or 0})

    @commands.Cog.listener()
    async def on_message_delete(self, m: discord.Message):
        if not m.guild or m.author.bot or await self._is_log_channel(m.channel):
            return
        files = f"{len(m.attachments)} tệp đính kèm" if m.attachments else None
        await self._log(m.guild, "🗑️ Tin nhắn bị xóa", C_ERR, f"Của {m.author.mention} trong {m.channel.mention}",
                        Nội_dung=m.content or "(không có chữ)", Tệp=files)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or after.author.bot or before.content == after.content:
            return
        if await self._is_log_channel(after.channel):
            return
        await self._log(after.guild, "✏️ Tin nhắn được sửa", C_WARN,
                        f"Của {after.author.mention} trong {after.channel.mention} · [Đến tin nhắn]({after.jump_url})",
                        Trước=before.content or "(trống)", Sau=after.content or "(trống)")

    @commands.Cog.listener()
    async def on_member_join(self, m: discord.Member):
        age = (utcnow() - m.created_at).days
        warn = " ⚠️ **tài khoản mới**" if age < 7 else ""
        await self._log(m.guild, "📥 Thành viên vào", C_OK, f"{m.mention} (`{m.id}`){warn}",
                        Tuổi_tài_khoản=f"{age} ngày", Tổng_thành_viên=m.guild.member_count)

    @commands.Cog.listener()
    async def on_member_remove(self, m: discord.Member):
        roles = ", ".join(r.name for r in m.roles if not r.is_default()) or None
        await self._log(m.guild, "📤 Thành viên rời", C_ERR, f"{m} (`{m.id}`)", Role=roles)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            added = [r.mention for r in set(after.roles) - set(before.roles)]
            removed = [r.mention for r in set(before.roles) - set(after.roles)]
            await self._log(after.guild, "🎭 Role thay đổi", C_INFO, after.mention,
                            Thêm=", ".join(added), Gỡ=", ".join(removed))
        elif before.nick != after.nick:
            await self._log(after.guild, "📝 Đổi nickname", C_INFO, after.mention,
                            Trước=before.nick or "(không có)", Sau=after.nick or "(không có)")

    @commands.Cog.listener()
    async def on_voice_state_update(self, m: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel == after.channel or m.bot:
            return
        if before.channel and after.channel:
            text = f"{m.mention} chuyển {before.channel.mention} → {after.channel.mention}"
        elif after.channel:
            text = f"{m.mention} vào {after.channel.mention}"
        else:
            text = f"{m.mention} rời {before.channel.mention}"
        await self._log(m.guild, "🔊 Voice", C_INFO, text)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, ch):
        await self._log(ch.guild, "➕ Tạo kênh", C_OK, f"{ch.mention if hasattr(ch, 'mention') else ch.name} (`{ch.type.name}`)")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, ch):
        await self._log(ch.guild, "➖ Xóa kênh", C_ERR, f"**{ch.name}** (`{ch.type.name}`)")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._log(role.guild, "➕ Tạo role", C_OK, role.mention)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._log(role.guild, "➖ Xóa role", C_ERR, f"**{role.name}**")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self._log(guild, "🔨 Ban", C_ERR, f"{user} (`{user.id}`)")

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await self._log(guild, "✅ Gỡ ban", C_OK, f"{user} (`{user.id}`)")


async def setup(bot):
    await bot.add_cog(Logs(bot))
