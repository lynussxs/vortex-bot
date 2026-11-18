"""AutoMod cuc bo (khong ton AI): spam, link moi, mention hang loat, tu cam, chong raid.
Tin nghi ngo (lua dao...) duoc chuyen cho module AI xem xet."""
import asyncio
import json
import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core.cases import record_case
from core.util import C_ERR, C_INFO, is_staff, norm, send_log, utcnow

INVITE_RE = re.compile(r"(?:discord\.gg|discord(?:app)?\.com/invite|dsc\.gg)/[A-Za-z0-9-]+", re.I)
SUS_RE = re.compile(
    r"(free\s*nitro|nitro\s*(gift|free)|steam\s*gift|gift\s*card|claim\s*(your|ur)|airdrop|"
    r"bit\.ly|tinyurl|cutt\.ly|grabify|iplogger|t\.me/|@everyone.*https?://)", re.I)
FEATURES = [("Chống spam", "spam"), ("Chặn link mời server khác", "invite"), ("Chống mention hàng loạt", "mention"),
            ("Chống raid", "raid"), ("Lọc từ cấm", "words")]
FEATURE_DEFAULT = {"spam": True, "invite": True, "mention": True, "raid": True, "words": True}
RAID_COUNT, RAID_WINDOW, RAID_LOCK_SECONDS = 8, 20, 600


class AutoMod(commands.Cog):
    automod = app_commands.Group(
        name="automod", description="Cấu hình AutoMod", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True))
    word = app_commands.Group(name="word", description="Danh sách từ cấm", parent=automod)

    def __init__(self, bot):
        self.bot = bot
        self.times = defaultdict(lambda: deque(maxlen=12))
        self.recent = defaultdict(lambda: deque(maxlen=8))
        self.joins = defaultdict(lambda: deque(maxlen=50))
        self.lockdown: set[int] = set()

    async def on(self, guild_id: int, feature: str) -> bool:
        return await self.bot.db.get_bool(guild_id, f"am_{feature}", FEATURE_DEFAULT[feature])

    async def words(self, guild_id: int) -> list[str]:
        try:
            return json.loads(await self.bot.db.get_setting(guild_id, "am_wordlist", "[]"))
        except json.JSONDecodeError:
            return []

    # ------------------------------------------------------------------ tin nhan
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        g, member = message.guild, message.author
        if is_staff(member, await self.bot.db.get_int(g.id, "role_mod")):
            return
        text = message.content or ""
        reason, minutes = None, 0

        if await self.on(g.id, "invite") and INVITE_RE.search(text):
            reason = "Gửi link mời server khác"
        elif await self.on(g.id, "mention") and len({m.id for m in message.mentions}) + len(message.role_mentions) >= 5:
            reason, minutes = "Mention hàng loạt", 10
        elif await self.on(g.id, "words") and (words := await self.words(g.id)):
            flat = norm(text)
            if any(w in flat for w in words):
                reason = "Dùng từ ngữ bị cấm"
        if not reason and await self.on(g.id, "spam"):
            now, key = time.monotonic(), (g.id, member.id)
            self.times[key].append(now)
            flat_text = text.strip().lower()
            self.recent[key].append((now, flat_text))
            burst = sum(1 for t in self.times[key] if now - t < 8)
            repeats = sum(1 for t, c in self.recent[key] if now - t < 20 and c and c == flat_text)
            if burst >= 6 or repeats >= 4:
                reason, minutes = "Spam tin nhắn", 5
                self.times[key].clear()
                self.recent[key].clear()

        if reason:
            return await self.punish(message, reason, minutes)

        if text and SUS_RE.search(text):  # nghi ngo lua dao -> nho AI xem
            ai = self.bot.get_cog("AI")
            if ai:
                asyncio.create_task(ai.review_message(message, ["Có mẫu link/cụm từ lừa đảo thường gặp"]))

    async def punish(self, message: discord.Message, reason: str, minutes: int = 0):
        member, g = message.author, message.guild
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        extra = {}
        if minutes:
            try:
                await member.timeout(timedelta(minutes=minutes), reason=f"AutoMod: {reason}")
                extra["Timeout"] = f"{minutes} phút"
            except discord.HTTPException:
                pass
        await record_case(self.bot, g, "AutoMod", member, self.bot.user, reason, extra)
        try:
            await message.channel.send(f"{member.mention} ⚠️ {reason}.", delete_after=8,
                                       allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ chong raid
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        g = member.guild
        if member.bot or not await self.on(g.id, "raid") or g.id in self.lockdown:
            return
        now = time.monotonic()
        dq = self.joins[g.id]
        dq.append(now)
        if sum(1 for t in dq if now - t < RAID_WINDOW) < RAID_COUNT:
            return
        self.lockdown.add(g.id)
        old = g.verification_level
        changed = False
        if old.value < discord.VerificationLevel.high.value:
            try:
                await g.edit(verification_level=discord.VerificationLevel.high, reason="AutoMod: nghi ngờ raid")
                changed = True
            except discord.HTTPException:
                pass
        e = discord.Embed(title="🚨 Nghi ngờ raid", color=C_ERR, timestamp=utcnow(),
                          description=f"{RAID_COUNT}+ tài khoản vào trong {RAID_WINDOW}s.\n"
                                      + ("Đã tạm nâng mức xác minh lên **High** trong 10 phút."
                                         if changed else "Hãy kiểm tra danh sách thành viên mới."))
        await send_log(self.bot, g, "ch_aistaff", e) or await send_log(self.bot, g, "ch_modlog", e)
        asyncio.create_task(self._end_lockdown(g, old if changed else None))

    async def _end_lockdown(self, guild: discord.Guild, old):
        await asyncio.sleep(RAID_LOCK_SECONDS)
        self.lockdown.discard(guild.id)
        if old is not None:
            try:
                await guild.edit(verification_level=old, reason="AutoMod: hết khóa raid")
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------ lenh
    @automod.command(name="status", description="Xem trạng thái AutoMod")
    async def status(self, interaction: discord.Interaction):
        lines = []
        for label, key in FEATURES:
            lines.append(f"{'🟢' if await self.on(interaction.guild_id, key) else '🔴'} {label}")
        n = len(await self.words(interaction.guild_id))
        lines.append(f"\n📝 {n} từ cấm. Staff (quyền Manage Messages/Moderate Members) được miễn.")
        await interaction.response.send_message(
            embed=discord.Embed(title="🛡️ AutoMod", description="\n".join(lines), color=C_INFO), ephemeral=True)

    @automod.command(name="toggle", description="Bật/tắt một tính năng AutoMod")
    @app_commands.choices(tinh_nang=[app_commands.Choice(name=n, value=v) for n, v in FEATURES])
    async def toggle(self, interaction: discord.Interaction, tinh_nang: app_commands.Choice[str], bat: bool):
        await self.bot.db.set_setting(interaction.guild_id, f"am_{tinh_nang.value}", bat)
        await interaction.response.send_message(
            f"✅ {tinh_nang.name}: **{'bật' if bat else 'tắt'}**", ephemeral=True)

    async def _save_words(self, guild_id, words):
        await self.bot.db.set_setting(guild_id, "am_wordlist", json.dumps(sorted(set(words)), ensure_ascii=False))

    @word.command(name="add", description="Thêm từ cấm (không phân biệt dấu/hoa thường)")
    async def word_add(self, interaction: discord.Interaction, tu: app_commands.Range[str, 2, 40]):
        key = norm(tu)
        if len(key) < 2:
            return await interaction.response.send_message("❌ Từ quá ngắn.", ephemeral=True)
        words = await self.words(interaction.guild_id)
        await self._save_words(interaction.guild_id, words + [key])
        await interaction.response.send_message(f"✅ Đã thêm `{key}`.", ephemeral=True)

    @word.command(name="remove", description="Xóa từ cấm")
    async def word_remove(self, interaction: discord.Interaction, tu: app_commands.Range[str, 2, 40]):
        key, words = norm(tu), await self.words(interaction.guild_id)
        if key not in words:
            return await interaction.response.send_message("Từ này không có trong danh sách.", ephemeral=True)
        words.remove(key)
        await self._save_words(interaction.guild_id, words)
        await interaction.response.send_message("✅ Đã xóa.", ephemeral=True)

    @word.command(name="list", description="Xem danh sách từ cấm")
    async def word_list(self, interaction: discord.Interaction):
        words = await self.words(interaction.guild_id)
        await interaction.response.send_message(
            ", ".join(f"`{w}`" for w in words) or "Chưa có từ cấm nào.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
