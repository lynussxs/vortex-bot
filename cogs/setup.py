"""/setup: cau hinh kenh/role cho bot (tu do tim theo ten kenh)."""
import discord
from discord import app_commands
from discord.ext import commands

from core.util import C_INFO, norm

CHANNEL_KINDS = [
    ("Nhật ký server (log-server)", "ch_log"),
    ("Nhật ký vi phạm cho staff (log-vi-phạm)", "ch_modlog"),
    ("Bản ghi xử phạt công khai (xử-phạt)", "ch_punish"),
    ("Kênh chào mừng (lối-vào)", "ch_welcome"),
    ("Kênh thông báo lên cấp", "ch_levelup"),
    ("Kênh staff nhận đề xuất của AI", "ch_aistaff"),
]
ROLE_KINDS = [("Role moderator", "role_mod"), ("Role tự gán khi vào server", "role_autorole")]
CHANNEL_HINTS = {  # ten kenh (da bo dau/emoji) chua tu khoa nay thi tu nhan
    "ch_log": "logserver", "ch_modlog": "logvipham", "ch_punish": "xuphat",
    "ch_welcome": "loivao", "ch_aistaff": "logvipham",
}
ROLE_HINTS = {"role_mod": "moderator", "role_autorole": "newcomer"}
LABELS = dict((v, k) for k, v in CHANNEL_KINDS + ROLE_KINDS)


class Setup(commands.Cog):
    setup = app_commands.Group(
        name="setup", description="Cấu hình bot", guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot

    @setup.command(name="auto", description="Tự dò kênh/role theo tên và cấu hình sẵn")
    @app_commands.describe(ghi_de="Ghi đè cả những mục đã cấu hình")
    async def auto(self, interaction: discord.Interaction, ghi_de: bool = False):
        g, db, lines = interaction.guild, self.bot.db, []
        for key, hint in CHANNEL_HINTS.items():
            if not ghi_de and await db.get_int(g.id, key):
                continue
            ch = next((c for c in g.text_channels if hint in norm(c.name)), None)
            if ch:
                await db.set_setting(g.id, key, ch.id)
                lines.append(f"✅ {LABELS[key]}: {ch.mention}")
        for key, hint in ROLE_HINTS.items():
            if not ghi_de and await db.get_int(g.id, key):
                continue
            role = next((r for r in g.roles if not r.managed and hint in norm(r.name)), None)
            if role:
                await db.set_setting(g.id, key, role.id)
                lines.append(f"✅ {LABELS[key]}: {role.mention}")
        text = "\n".join(lines) or "Không dò thêm được mục nào (có thể đã cấu hình sẵn). Dùng `/setup show` để xem."
        await interaction.response.send_message(text, ephemeral=True)

    @setup.command(name="channel", description="Chọn kênh cho một chức năng")
    @app_commands.choices(loai=[app_commands.Choice(name=n, value=v) for n, v in CHANNEL_KINDS])
    async def channel(self, interaction: discord.Interaction, loai: app_commands.Choice[str],
                      kenh: discord.TextChannel):
        await self.bot.db.set_setting(interaction.guild_id, loai.value, kenh.id)
        await interaction.response.send_message(f"✅ {loai.name} → {kenh.mention}", ephemeral=True)

    @setup.command(name="role", description="Chọn role cho một chức năng")
    @app_commands.choices(loai=[app_commands.Choice(name=n, value=v) for n, v in ROLE_KINDS])
    async def role(self, interaction: discord.Interaction, loai: app_commands.Choice[str], role: discord.Role):
        await self.bot.db.set_setting(interaction.guild_id, loai.value, role.id)
        await interaction.response.send_message(f"✅ {loai.name} → {role.mention}", ephemeral=True)

    @setup.command(name="show", description="Xem cấu hình hiện tại")
    async def show(self, interaction: discord.Interaction):
        g, db = interaction.guild, self.bot.db
        lines = []
        for name, key in CHANNEL_KINDS:
            cid = await db.get_int(g.id, key)
            lines.append(f"**{name}**: {f'<#{cid}>' if cid else '_chưa đặt_'}")
        for name, key in ROLE_KINDS:
            rid = await db.get_int(g.id, key)
            lines.append(f"**{name}**: {f'<@&{rid}>' if rid else '_chưa đặt_'}")
        pub = await db.get_bool(g.id, "punish_public", True)
        lines.append(f"**Đăng bản ghi xử phạt công khai**: {'bật' if pub else 'tắt'}")
        await interaction.response.send_message(
            embed=discord.Embed(title="⚙️ Cấu hình bot", description="\n".join(lines), color=C_INFO), ephemeral=True)

    @setup.command(name="congkhai", description="Bật/tắt đăng bản ghi xử phạt vào kênh công khai")
    async def congkhai(self, interaction: discord.Interaction, bat: bool):
        await self.bot.db.set_setting(interaction.guild_id, "punish_public", bat)
        await interaction.response.send_message(f"✅ Đã {'bật' if bat else 'tắt'}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Setup(bot))
