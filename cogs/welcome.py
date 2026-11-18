"""Chao mung, tam biet va role tu dong khi vao server."""
import discord
from discord import app_commands
from discord.ext import commands

from core.util import C_INFO, NO_MENTIONS, send_log, utcnow

DEFAULT_WELCOME = "Chào mừng {user} đến với **{server}**! Bạn là thành viên thứ **{count}**. Hãy đọc luật và nhận role nhé 🎉"
DEFAULT_GOODBYE = "**{name}** đã rời server. Hẹn gặp lại! 👋"


def fill(template: str, member: discord.abc.User, guild: discord.Guild) -> str:
    for key, val in {"{user}": member.mention, "{name}": getattr(member, "display_name", str(member)),
                     "{server}": guild.name, "{count}": str(guild.member_count)}.items():
        template = template.replace(key, val)
    return template


class Welcome(commands.Cog):
    welcome = app_commands.Group(
        name="welcome", description="Tin chào mừng", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True))
    autorole = app_commands.Group(
        name="autorole", description="Role tự gán khi vào server", guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True))

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        g, db = member.guild, self.bot.db
        rid = await db.get_int(g.id, "role_autorole")
        role = g.get_role(rid) if rid else None
        if role:
            try:
                await member.add_roles(role, reason="Auto-role")
            except discord.HTTPException:
                pass
        await self._send_welcome(member)

    async def _send_welcome(self, member):
        g, db = member.guild, self.bot.db
        text = fill(await db.get_setting(g.id, "welcome_msg", DEFAULT_WELCOME), member, g)
        e = discord.Embed(description=text, color=C_INFO, timestamp=utcnow())
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=f"{g.name} • Thành viên #{g.member_count}")
        cid = await db.get_int(g.id, "ch_welcome")
        ch = g.get_channel(cid) if cid else None
        if ch:
            try:
                await ch.send(content=member.mention, embed=e, allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        g, db = member.guild, self.bot.db
        if member.bot or not await db.get_bool(g.id, "goodbye_enabled", False):
            return
        text = fill(await db.get_setting(g.id, "goodbye_msg", DEFAULT_GOODBYE), member, g)
        await send_log(self.bot, g, "ch_welcome", discord.Embed(description=text, color=C_INFO))

    @welcome.command(name="message", description="Đặt nội dung chào mừng ({user} {name} {server} {count})")
    async def w_message(self, interaction: discord.Interaction, noi_dung: app_commands.Range[str, 1, 1000]):
        await self.bot.db.set_setting(interaction.guild_id, "welcome_msg", noi_dung)
        await interaction.response.send_message("✅ Đã lưu. Dùng `/welcome test` để xem thử.", ephemeral=True)

    @welcome.command(name="goodbye", description="Bật/tắt tin tạm biệt khi có người rời server")
    async def w_goodbye(self, interaction: discord.Interaction, bat: bool):
        await self.bot.db.set_setting(interaction.guild_id, "goodbye_enabled", bat)
        await interaction.response.send_message(f"✅ Tin tạm biệt đã {'bật' if bat else 'tắt'}.", ephemeral=True)

    @welcome.command(name="test", description="Gửi thử tin chào mừng cho bạn")
    async def w_test(self, interaction: discord.Interaction):
        await interaction.response.send_message("📨 Đã gửi thử vào kênh chào mừng.", ephemeral=True)
        await self._send_welcome(interaction.user)

    @autorole.command(name="set", description="Chọn role tự gán cho thành viên mới")
    async def ar_set(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ Role này cao hơn role của bot.", ephemeral=True)
        await self.bot.db.set_setting(interaction.guild_id, "role_autorole", role.id)
        await interaction.response.send_message(f"✅ Thành viên mới sẽ nhận {role.mention}", ephemeral=True,
                                                allowed_mentions=NO_MENTIONS)

    @autorole.command(name="clear", description="Tắt role tự gán")
    async def ar_clear(self, interaction: discord.Interaction):
        await self.bot.db.set_setting(interaction.guild_id, "role_autorole", None)
        await interaction.response.send_message("✅ Đã tắt.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
