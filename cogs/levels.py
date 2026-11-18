"""Level + XP (nhu Arcane): XP theo tin nhan, /rank, /leaderboard, thuong role khi len cap."""
import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.db import level_from_xp
from core.util import C_INFO, NO_MENTIONS, progress_bar

XP_COOLDOWN = 60  # giay giua hai lan nhan XP


class Levels(commands.Cog):
    levelrole = app_commands.Group(
        name="levelrole", description="Role thưởng khi lên cấp", guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True))
    xp = app_commands.Group(
        name="xp", description="Chỉnh XP thủ công", guild_only=True,
        default_permissions=discord.Permissions(administrator=True))

    def __init__(self, bot):
        self.bot = bot
        self._last: dict[tuple[int, int], float] = {}

    # ------------------------------------------------------------------ nhan XP
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or len(message.content.strip()) < 3:
            return
        gid = message.guild.id
        if not await self.bot.db.get_bool(gid, "xp_enabled", True):
            return
        key, now = (gid, message.author.id), time.monotonic()
        if now - self._last.get(key, 0) < XP_COOLDOWN:
            return
        self._last[key] = now
        old, new, _ = await self.bot.db.add_xp(gid, message.author.id, random.randint(15, 25))
        if new > old:
            await self._level_up(message, new)

    async def _level_up(self, message: discord.Message, level: int):
        member, guild = message.author, message.guild
        rewards = [rid for lvl, rid in await self.bot.db.level_roles(guild.id) if lvl <= level]
        roles = [r for r in (guild.get_role(rid) for rid in rewards) if r and r not in member.roles]
        extra = ""
        if roles:
            try:
                await member.add_roles(*roles, reason=f"Lên cấp {level}")
                extra = "\n🎁 Nhận role: " + ", ".join(r.mention for r in roles)
            except discord.HTTPException:
                pass
        cid = await self.bot.db.get_int(guild.id, "ch_levelup")
        channel = guild.get_channel(cid) if cid else message.channel
        try:
            await channel.send(f"🎉 {member.mention} đã lên **cấp {level}**!{extra}",
                               allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ lenh
    @app_commands.command(name="rank", description="Xem cấp độ và XP")
    @app_commands.describe(member="Người cần xem (mặc định là bạn)")
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        member = member or interaction.user
        total = await self.bot.db.get_xp(interaction.guild_id, member.id)
        level, cur, need = level_from_xp(total)
        pos = await self.bot.db.rank_position(interaction.guild_id, member.id)
        e = discord.Embed(title=f"📈 {member.display_name}", color=C_INFO)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Cấp", value=f"**{level}**")
        e.add_field(name="Hạng", value=f"**#{pos}**")
        e.add_field(name="Tổng XP", value=f"**{total:,}**")
        e.add_field(name=f"Tiến độ lên cấp {level + 1}", value=f"`{progress_bar(cur, need)}` {cur:,}/{need:,} XP",
                    inline=False)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="leaderboard", description="Bảng xếp hạng XP")
    @app_commands.describe(page="Trang (mỗi trang 10 người)")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction, page: app_commands.Range[int, 1, 100] = 1):
        rows = await self.bot.db.leaderboard(interaction.guild_id, 10, (page - 1) * 10)
        if not rows:
            return await interaction.response.send_message("Chưa có dữ liệu trang này.", ephemeral=True)
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, r in enumerate(rows, (page - 1) * 10 + 1):
            lines.append(f"{medals.get(i, f'`{i}.`')} <@{r['user_id']}> · cấp **{level_from_xp(r['xp'])[0]}** · {r['xp']:,} XP")
        e = discord.Embed(title="🏆 Bảng xếp hạng", description="\n".join(lines), color=C_INFO)
        e.set_footer(text=f"Trang {page}")
        await interaction.response.send_message(embed=e, allowed_mentions=NO_MENTIONS)

    @levelrole.command(name="add", description="Gán role thưởng cho một cấp")
    @app_commands.describe(level="Cấp độ", role="Role sẽ nhận")
    async def lr_add(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 500], role: discord.Role):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ Role này cao hơn role của bot nên bot không gán được.", ephemeral=True)
        await self.bot.db.set_level_role(interaction.guild_id, level, role.id)
        await interaction.response.send_message(f"✅ Cấp **{level}** → {role.mention}", ephemeral=True)

    @levelrole.command(name="remove", description="Xóa role thưởng của một cấp")
    async def lr_remove(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 500]):
        ok = await self.bot.db.remove_level_role(interaction.guild_id, level)
        await interaction.response.send_message("✅ Đã xóa." if ok else "Không có role thưởng ở cấp này.", ephemeral=True)

    @levelrole.command(name="list", description="Danh sách role thưởng")
    async def lr_list(self, interaction: discord.Interaction):
        rows = await self.bot.db.level_roles(interaction.guild_id)
        text = "\n".join(f"Cấp **{lvl}** → <@&{rid}>" for lvl, rid in rows) or "Chưa có role thưởng nào."
        await interaction.response.send_message(text, ephemeral=True)

    @xp.command(name="add", description="Cộng/trừ XP cho một người")
    async def xp_add(self, interaction: discord.Interaction, member: discord.Member,
                     amount: app_commands.Range[int, -1000000, 1000000]):
        _, new, total = await self.bot.db.add_xp(interaction.guild_id, member.id, amount)
        await interaction.response.send_message(f"✅ {member.mention}: {total:,} XP (cấp {new}).", ephemeral=True,
                                                allowed_mentions=NO_MENTIONS)

    @xp.command(name="set", description="Đặt XP cho một người")
    async def xp_set(self, interaction: discord.Interaction, member: discord.Member,
                     amount: app_commands.Range[int, 0, 10000000]):
        _, new, total = await self.bot.db.set_xp(interaction.guild_id, member.id, amount)
        await interaction.response.send_message(f"✅ {member.mention}: {total:,} XP (cấp {new}).", ephemeral=True,
                                                allowed_mentions=NO_MENTIONS)

    @app_commands.command(name="levels", description="Bật/tắt hệ thống XP")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def levels(self, interaction: discord.Interaction, bat: bool):
        await self.bot.db.set_setting(interaction.guild_id, "xp_enabled", bat)
        await interaction.response.send_message(f"✅ Hệ thống XP đã {'bật' if bat else 'tắt'}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Levels(bot))
