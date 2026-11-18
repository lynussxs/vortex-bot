"""Ghi case xu phat: luu DB, log noi bo (staff) va ban ghi gon cong khai (khong chep noi dung tin nhan)."""
import discord

from core.util import C_WARN, send_log, utcnow


async def record_case(bot, guild, action, target, mod, reason, extra=None, public=True, color=C_WARN) -> int:
    reason = (reason or "Không có lý do")[:1000]
    case_id = await bot.db.add_case(guild.id, target.id, mod.id, action, reason)

    e = discord.Embed(title=f"Case #{case_id} · {action}", color=color, timestamp=utcnow())
    e.add_field(name="Thành viên", value=f"{target} (`{target.id}`)")
    e.add_field(name="Người xử lý", value=getattr(mod, "mention", str(mod)))
    for k, v in (extra or {}).items():
        e.add_field(name=k, value=str(v))
    e.add_field(name="Lý do", value=reason, inline=False)
    await send_log(bot, guild, "ch_modlog", e)

    if public and await bot.db.get_bool(guild.id, "punish_public", True):
        p = discord.Embed(title=f"⚠️ {action}", color=color, timestamp=utcnow())
        p.add_field(name="Thành viên", value=str(target))
        for k, v in (extra or {}).items():
            p.add_field(name=k, value=str(v))
        p.add_field(name="Lý do", value=reason, inline=False)
        p.set_footer(text="Ghi nhận tự động")
        await send_log(bot, guild, "ch_punish", p)
    return case_id
