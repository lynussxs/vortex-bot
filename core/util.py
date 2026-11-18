"""Ham dung chung."""
import re
import unicodedata
from datetime import timedelta

import discord

C_OK, C_ERR, C_INFO, C_WARN = 0x2ECC71, 0xE74C3C, 0x5B8DEF, 0xE67E22
NO_MENTIONS = discord.AllowedMentions.none()
_DUR = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.I)
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def utcnow():
    return discord.utils.utcnow()


def parse_duration(text: str):
    """'10m', '2h', '1d' -> timedelta. Sai dinh dang -> None."""
    m = _DUR.match(text or "")
    return timedelta(seconds=int(m.group(1)) * _UNIT[m.group(2).lower()]) if m else None


def fmt_duration(td: timedelta) -> str:
    s = int(td.total_seconds())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return " ".join(f"{v}{u}" for v, u in ((d, "d"), (h, "h"), (m, "m"), (s, "s")) if v) or "0s"


def norm(text: str) -> str:
    """Bo dau, bo emoji/ky hieu, chu thuong: '📊・log-vi-phạm' -> 'logvipham'."""
    t = unicodedata.normalize("NFKC", text).replace("đ", "d").replace("Đ", "D")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", t.lower())


def progress_bar(cur: int, total: int, width: int = 12) -> str:
    filled = int(width * min(cur / max(total, 1), 1))
    return "█" * filled + "░" * (width - filled)


def hierarchy_error(guild: discord.Guild, actor: discord.Member, target: discord.Member):
    """Tra ve chuoi loi neu actor khong the xu ly target, nguoc lai None."""
    if target.id == actor.id:
        return "Bạn không thể tự xử lý chính mình."
    if target.id == guild.me.id:
        return "Mình không tự xử lý mình được 😅"
    if target.id == guild.owner_id:
        return "Không thể xử lý chủ server."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "Role của người này cao hơn hoặc bằng bạn."
    if target.top_role >= guild.me.top_role:
        return "Role của bot thấp hơn người này nên không xử lý được. Hãy kéo role bot lên cao hơn."
    return None


def is_staff(member: discord.Member, mod_role_id: int | None = None) -> bool:
    p = member.guild_permissions
    if p.administrator or p.manage_messages or p.moderate_members:
        return True
    return bool(mod_role_id and any(r.id == mod_role_id for r in member.roles))


async def send_log(bot, guild: discord.Guild, key: str, embed: discord.Embed | None = None, **kwargs):
    """Gui vao kenh da cau hinh (settings[key]). Khong co kenh thi bo qua."""
    cid = await bot.db.get_int(guild.id, key)
    channel = guild.get_channel(cid) if cid else None
    if channel is None or not hasattr(channel, "send"):
        return None
    try:
        return await channel.send(embed=embed, allowed_mentions=NO_MENTIONS, **kwargs)
    except discord.HTTPException:
        return None
