"""Tien ich: /help /ping /serverinfo /userinfo /avatar /poll /embed /announce"""
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.util import C_INFO

NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Danh sách chức năng của bot")
    async def help(self, interaction: discord.Interaction):
        e = discord.Embed(title="📖 Trợ giúp", color=C_INFO, description=(
            "**Mọi người**\n`/rank` `/leaderboard` `/hoi` `/serverinfo` `/userinfo` `/avatar` `/ping`\n"
            "💬 **Hỏi AI:** @tên bot rồi hỏi thẳng, ví dụ _@bot server có những kênh game nào?_\n\n"
            "**Staff**\n`/ban` `/unban` `/kick` `/timeout` `/untimeout` `/warn` `/warnings` `/clearwarns`\n"
            "`/purge` `/slowmode` `/lock` `/unlock` `/tomtat` `/poll` `/embed` `/announce`\n\n"
            "**Quản trị**\n`/setup` `/automod` `/levelrole` `/xp` `/levels` `/welcome` `/autorole` `/ai`"))
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="ping", description="Kiểm tra độ trễ của bot")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong! `{self.bot.latency * 1000:.0f}ms`", ephemeral=True)

    @app_commands.command(name="serverinfo", description="Thông tin server")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        e = discord.Embed(title=g.name, color=C_INFO, description=g.description or None)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name="Thành viên", value=f"{g.member_count:,}")
        e.add_field(name="Kênh", value=str(len(g.channels)))
        e.add_field(name="Role", value=str(len(g.roles)))
        e.add_field(name="Boost", value=f"Cấp {g.premium_tier} ({g.premium_subscription_count})")
        e.add_field(name="Ngày tạo", value=discord.utils.format_dt(g.created_at, "D"))
        e.add_field(name="Chủ server", value=f"<@{g.owner_id}>")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="userinfo", description="Thông tin một thành viên")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        m = member or interaction.user
        e = discord.Embed(title=str(m), color=m.color or C_INFO)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="ID", value=str(m.id))
        e.add_field(name="Tạo tài khoản", value=discord.utils.format_dt(m.created_at, "R"))
        e.add_field(name="Vào server", value=discord.utils.format_dt(m.joined_at, "R") if m.joined_at else "?")
        roles = [r.mention for r in reversed(m.roles) if not r.is_default()][:15]
        e.add_field(name=f"Role ({len(m.roles) - 1})", value=" ".join(roles) or "Không có", inline=False)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="avatar", description="Xem avatar")
    async def avatar(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        m = member or interaction.user
        e = discord.Embed(title=f"Avatar của {m.display_name}", color=C_INFO)
        e.set_image(url=m.display_avatar.url)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="poll", description="Tạo bình chọn")
    @app_commands.describe(cau_hoi="Câu hỏi", lua_chon="Các lựa chọn, cách nhau bằng dấu ; (tối đa 9)")
    @app_commands.guild_only()
    async def poll(self, interaction: discord.Interaction, cau_hoi: app_commands.Range[str, 1, 200], lua_chon: str):
        options = [o.strip() for o in lua_chon.split(";") if o.strip()][:9]
        if len(options) < 2:
            return await interaction.response.send_message("❌ Cần ít nhất 2 lựa chọn, cách nhau bằng `;`.", ephemeral=True)
        e = discord.Embed(title=f"📊 {cau_hoi}", color=C_INFO,
                          description="\n".join(f"{NUM[i]} {o}" for i, o in enumerate(options)))
        e.set_footer(text=f"Bình chọn bởi {interaction.user.display_name}")
        await interaction.response.send_message(embed=e)
        msg = await interaction.original_response()
        for i in range(len(options)):
            await msg.add_reaction(NUM[i])

    @app_commands.command(name="embed", description="Gửi một embed tùy chỉnh")
    @app_commands.describe(tieu_de="Tiêu đề", noi_dung="Nội dung (dùng \\n để xuống dòng)", mau="Màu hex, ví dụ B197FC",
                           kenh="Kênh gửi (mặc định kênh hiện tại)")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def embed(self, interaction: discord.Interaction, tieu_de: app_commands.Range[str, 1, 256],
                    noi_dung: app_commands.Range[str, 1, 3000], mau: str = "5B8DEF",
                    kenh: Optional[discord.TextChannel] = None):
        try:
            color = int(mau.lstrip("#"), 16)
        except ValueError:
            return await interaction.response.send_message("❌ Màu không hợp lệ (ví dụ `B197FC`).", ephemeral=True)
        e = discord.Embed(title=tieu_de, description=noi_dung.replace("\\n", "\n"), color=color)
        try:
            await (kenh or interaction.channel).send(embed=e)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Bot không gửi được vào kênh đó.", ephemeral=True)
        await interaction.response.send_message("✅ Đã gửi.", ephemeral=True)

    @app_commands.command(name="announce", description="Gửi thông báo vào một kênh")
    @app_commands.describe(kenh="Kênh nhận thông báo", noi_dung="Nội dung", ping="Ping cả server?")
    @app_commands.choices(ping=[app_commands.Choice(name="Không ping", value="none"),
                                app_commands.Choice(name="@everyone", value="everyone"),
                                app_commands.Choice(name="@here", value="here")])
    @app_commands.default_permissions(mention_everyone=True)
    @app_commands.checks.has_permissions(mention_everyone=True)
    @app_commands.guild_only()
    async def announce(self, interaction: discord.Interaction, kenh: discord.TextChannel,
                       noi_dung: app_commands.Range[str, 1, 1800], ping: Optional[app_commands.Choice[str]] = None):
        prefix = {"everyone": "@everyone ", "here": "@here "}.get(ping.value if ping else "none", "")
        try:
            await kenh.send(prefix + noi_dung, allowed_mentions=discord.AllowedMentions(everyone=bool(prefix)))
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Bot không gửi được vào kênh đó.", ephemeral=True)
        await interaction.response.send_message(f"✅ Đã gửi vào {kenh.mention}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Utility(bot))
