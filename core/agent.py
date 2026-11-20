"""Cong cu de AI thuc hien thao tac quan ly server.

NGUYEN TAC AN TOAN: moi cong cu kiem tra quyen Discord cua NGUOI HOI (khong tin loi cua AI),
ton trong thu bac role, ghi log, va cac thao tac pha huy (xoa/kick/ban/purge) phai co nguoi hoi bam xac nhan.
"""
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Awaitable, Callable

import discord

from core.cases import record_case
from core.util import C_OK, C_WARN, NO_MENTIONS, hierarchy_error, norm, send_log, utcnow

STAFF_PERMS = ("manage_roles", "manage_channels", "manage_messages", "moderate_members",
               "kick_members", "ban_members", "manage_guild")
COLOR_NAMES = {"do": "E74C3C", "cam": "E67E22", "vang": "F1C40F", "xanhla": "2ECC71", "xanhduong": "3498DB",
               "tim": "9B59B6", "hong": "FD79A8", "trang": "FFFFFF", "den": "23272A", "xanhngoc": "1ABC9C",
               "nau": "A0522D", "xam": "95A5A6", "bac": "BDC3C7",
               "red": "E74C3C", "orange": "E67E22", "yellow": "F1C40F", "green": "2ECC71", "blue": "3498DB",
               "purple": "9B59B6", "pink": "FD79A8", "white": "FFFFFF", "black": "23272A", "brown": "A0522D",
               "gray": "95A5A6", "grey": "95A5A6", "teal": "1ABC9C", "cyan": "1ABC9C"}
PERM_LABELS = {"manage_roles": "Quản lý Role", "manage_channels": "Quản lý Kênh", "manage_messages": "Quản lý Tin nhắn",
               "moderate_members": "Timeout thành viên", "kick_members": "Kick", "ban_members": "Ban",
               "manage_guild": "Quản lý Server", "administrator": "Administrator"}


@dataclass
class Ctx:
    bot: object
    guild: discord.Guild
    asker: discord.Member
    channel: discord.abc.Messageable


@dataclass
class Confirm:
    text: str
    perm: str
    run: Callable[[], Awaitable[str]]
    audit: str


# ------------------------------------------------------------------ tien ich
def parse_color(text) -> int | None:
    t = str(text).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", t):
        return int(t, 16)
    if re.fullmatch(r"[0-9a-fA-F]{3}", t):
        return int("".join(c * 2 for c in t), 16)
    h = COLOR_NAMES.get(norm(str(text)))
    return int(h, 16) if h else None


def has_perm(member: discord.Member, perm) -> bool:
    gp = member.guild_permissions
    if gp.administrator or perm is None:
        return True
    if perm == "__staff__":
        return any(getattr(gp, p, False) for p in STAFF_PERMS)
    return bool(getattr(gp, perm, False))


def asker_summary(member: discord.Member) -> str:
    gp = member.guild_permissions
    if gp.administrator:
        perms = "Administrator (toàn quyền)"
    else:
        perms = ", ".join(PERM_LABELS[p] for p in STAFF_PERMS if getattr(gp, p, False)) or "không có quyền quản lý nào (thành viên thường)"
    owner = " (CHỦ SERVER)" if member.id == member.guild.owner_id else ""
    return f"{member.display_name} (ID {member.id}){owner}; quyền quản lý: {perms}; role cao nhất: {member.top_role.name}"


def find_role(guild, text):
    t = str(text).strip()
    m = re.search(r"\d{15,}", t)
    if m:
        role = guild.get_role(int(m.group()))
        return (role, None) if role else (None, f"Không có role nào có ID {m.group()}.")
    key = norm(t)
    if not key:
        return None, "Thiếu tên role."
    exact = [r for r in guild.roles if norm(r.name) == key]
    cands = exact or [r for r in guild.roles if key in norm(r.name)]
    if len(cands) == 1:
        return cands[0], None
    if not cands:
        return None, f"Không tìm thấy role '{t}'. Hãy dùng list_roles để xem danh sách."
    return None, "Có nhiều role khớp: " + ", ".join(f"{r.name} (ID {r.id})" for r in cands[:8]) + ". Hãy chỉ rõ bằng ID."


def find_member(guild, text):
    t = str(text).strip()
    m = re.search(r"\d{15,}", t)
    if m:
        mem = guild.get_member(int(m.group()))
        return (mem, None) if mem else (None, f"Không có thành viên nào có ID {m.group()} trong server.")
    key = norm(t)
    if not key:
        return None, "Thiếu tên thành viên."
    def names(x): return {norm(x.display_name), norm(x.name)}
    exact = [x for x in guild.members if key in names(x)]
    cands = exact or [x for x in guild.members if any(key in n for n in names(x))]
    if len(cands) == 1:
        return cands[0], None
    if not cands:
        return None, f"Không tìm thấy thành viên '{t}'."
    return None, "Có nhiều người khớp: " + ", ".join(f"{x.display_name} (ID {x.id})" for x in cands[:8]) + ". Hãy chỉ rõ bằng ID hoặc @mention."


def find_channel(guild, text, kinds=None):
    t = str(text).strip()
    m = re.search(r"\d{15,}", t)
    if m:
        ch = guild.get_channel(int(m.group()))
        return (ch, None) if ch else (None, f"Không có kênh nào có ID {m.group()}.")
    key = norm(t)
    pool = [c for c in guild.channels if kinds is None or c.type.name in kinds]
    exact = [c for c in pool if norm(c.name) == key]
    cands = exact or ([c for c in pool if key in norm(c.name)] if key else [])
    if len(cands) == 1:
        return cands[0], None
    if not cands:
        return None, f"Không tìm thấy kênh '{t}'. Hãy dùng list_channels để xem danh sách."
    return None, "Có nhiều kênh khớp: " + ", ".join(f"{c.name} (ID {c.id})" for c in cands[:8]) + ". Hãy chỉ rõ bằng ID."


def role_error(ctx: Ctx, role: discord.Role):
    g, a = ctx.guild, ctx.asker
    if role.is_default():
        return "Không thể thao tác với @everyone."
    if role >= g.me.top_role:
        return f"Role '{role.name}' cao hơn hoặc bằng role của bot. Hãy kéo role bot lên cao hơn trong Server Settings → Roles."
    if a.id != g.owner_id and role >= a.top_role:
        return f"Role '{role.name}' cao hơn hoặc bằng role cao nhất của {a.display_name}."
    return None


# ------------------------------------------------------------------ dang ky cong cu
TOOLS: dict = {}


def P(name, typ, desc, req=False, enum=None):
    return name, typ, desc, req, enum


def tool(name, desc, params=(), perm="__staff__"):
    def deco(fn):
        TOOLS[name] = {"fn": fn, "desc": desc, "params": params, "perm": perm}
        return fn
    return deco


def schema(name: str) -> dict:
    spec = TOOLS[name]
    props, req = {}, []
    for pname, typ, desc, required, enum in spec["params"]:
        props[pname] = {"type": typ, "description": desc}
        if enum:
            props[pname]["enum"] = enum
        if required:
            req.append(pname)
    return {"type": "function", "function": {"name": name, "description": spec["desc"],
            "parameters": {"type": "object", "properties": props, "required": req}}}


def available_tools(asker: discord.Member) -> list:
    return [schema(n) for n, s in TOOLS.items() if has_perm(asker, s["perm"])]


# ------------------------------------------------------------------ doc thong tin
@tool("list_roles", "Liệt kê role của server: tên, ID, màu, vị trí, số thành viên.")
async def t_list_roles(ctx: Ctx):
    rows = [f"{r.name} | ID {r.id} | #{r.color.value:06x} | vị trí {r.position} | {len(r.members)} người"
            for r in sorted(ctx.guild.roles, key=lambda r: -r.position) if not r.is_default()]
    return "\n".join(rows[:70]) or "Không có role."


@tool("list_channels", "Liệt kê category và kênh của server kèm ID.")
async def t_list_channels(ctx: Ctx):
    out = []
    for cat in ctx.guild.categories:
        out.append(f"[{cat.name}] ID {cat.id}")
        out += [f"  - {c.name} ({c.type.name}) ID {c.id}" for c in cat.channels]
    rest = [c for c in ctx.guild.channels if c.category is None and not isinstance(c, discord.CategoryChannel)]
    out += [f"(không category) {c.name} ({c.type.name}) ID {c.id}" for c in rest]
    return "\n".join(out[:90])


@tool("member_info", "Xem thông tin một thành viên (role, ngày tạo/vào).", [P("member", "string", "Tên, @mention hoặc ID", True)])
async def t_member_info(ctx: Ctx, member: str):
    m, err = find_member(ctx.guild, member)
    if err:
        return "❌ " + err
    roles = ", ".join(r.name for r in reversed(m.roles) if not r.is_default()) or "không có"
    return (f"{m.display_name} (ID {m.id}); tài khoản tạo {m.created_at:%d/%m/%Y}; vào server "
            f"{m.joined_at:%d/%m/%Y}" if m.joined_at else f"{m.display_name} (ID {m.id})") + f"; role: {roles}"


# ------------------------------------------------------------------ role
@tool("edit_role", "Sửa role: đổi tên, màu, hiển thị riêng (hoist), cho phép mention. Màu nhận mã hex (#E74C3C) hoặc tên màu tiếng Việt.",
      [P("role", "string", "Tên hoặc ID role", True), P("name", "string", "Tên mới"),
       P("color", "string", "Màu: mã hex hoặc tên như đỏ, cam, xanh lá"), P("hoist", "boolean", "Hiện riêng trong danh sách thành viên"),
       P("mentionable", "boolean", "Cho phép @mention role")], perm="manage_roles")
async def t_edit_role(ctx: Ctx, role: str, name=None, color=None, hoist=None, mentionable=None):
    r, err = find_role(ctx.guild, role)
    if err:
        return "❌ " + err
    if e := role_error(ctx, r):
        return "❌ " + e
    kw, done = {}, []
    if name:
        kw["name"] = str(name)[:100]
        done.append(f"tên → {name}")
    if color is not None:
        c = parse_color(color)
        if c is None:
            return f"❌ Không hiểu màu '{color}'. Dùng mã hex như #E74C3C hoặc tên: đỏ, cam, vàng, xanh lá, xanh dương, tím, hồng."
        kw["colour"] = discord.Colour(c)
        done.append(f"màu → #{c:06x}")
    if hoist is not None:
        kw["hoist"] = bool(hoist)
        done.append(f"hoist → {bool(hoist)}")
    if mentionable is not None:
        kw["mentionable"] = bool(mentionable)
        done.append(f"mentionable → {bool(mentionable)}")
    if not kw:
        return "❌ Không có gì để sửa (cần name, color, hoist hoặc mentionable)."
    await r.edit(reason=f"AI theo yêu cầu của {ctx.asker}", **kw)
    return f"✅ Đã sửa role {r.name}: " + ", ".join(done)


@tool("create_role", "Tạo role mới (không có quyền đặc biệt). Màu hex hoặc tên màu.",
      [P("name", "string", "Tên role", True), P("color", "string", "Màu"), P("hoist", "boolean", "Hiện riêng"),
       P("mentionable", "boolean", "Cho mention")], perm="manage_roles")
async def t_create_role(ctx: Ctx, name: str, color=None, hoist=False, mentionable=False):
    c = parse_color(color) if color is not None else 0
    if c is None:
        return f"❌ Không hiểu màu '{color}'."
    r = await ctx.guild.create_role(name=str(name)[:100], colour=discord.Colour(c), hoist=bool(hoist),
                                    mentionable=bool(mentionable), reason=f"AI theo yêu cầu của {ctx.asker}")
    return f"✅ Đã tạo role {r.name} (ID {r.id}, màu #{c:06x}). Role mới nằm cuối danh sách; kéo lên vị trí mong muốn trong Server Settings."


@tool("delete_role", "Xóa một role (cần người dùng bấm xác nhận).", [P("role", "string", "Tên hoặc ID role", True)], perm="manage_roles")
async def t_delete_role(ctx: Ctx, role: str):
    r, err = find_role(ctx.guild, role)
    if err:
        return "❌ " + err
    if e := role_error(ctx, r):
        return "❌ " + e

    async def run():
        name = r.name
        await r.delete(reason=f"AI theo yêu cầu của {ctx.asker}")
        return f"✅ Đã xóa role {name}."
    return Confirm(f"Xóa role **{r.name}** ({len(r.members)} thành viên đang giữ)?", "manage_roles", run, "delete_role")


async def _role_member(ctx: Ctx, member, role, add: bool):
    m, err = find_member(ctx.guild, member)
    if err:
        return "❌ " + err
    r, err = find_role(ctx.guild, role)
    if err:
        return "❌ " + err
    if e := role_error(ctx, r):
        return "❌ " + e
    if add:
        await m.add_roles(r, reason=f"AI theo yêu cầu của {ctx.asker}")
        return f"✅ Đã gán role {r.name} cho {m.display_name}."
    await m.remove_roles(r, reason=f"AI theo yêu cầu của {ctx.asker}")
    return f"✅ Đã gỡ role {r.name} khỏi {m.display_name}."


@tool("give_role", "Gán role cho một thành viên.", [P("member", "string", "Tên, @mention hoặc ID", True),
      P("role", "string", "Tên hoặc ID role", True)], perm="manage_roles")
async def t_give_role(ctx: Ctx, member: str, role: str):
    return await _role_member(ctx, member, role, True)


@tool("remove_role", "Gỡ role khỏi một thành viên.", [P("member", "string", "Tên, @mention hoặc ID", True),
      P("role", "string", "Tên hoặc ID role", True)], perm="manage_roles")
async def t_remove_role(ctx: Ctx, member: str, role: str):
    return await _role_member(ctx, member, role, False)


# ------------------------------------------------------------------ kenh
@tool("create_channel", "Tạo kênh hoặc category mới.", [P("name", "string", "Tên kênh", True),
      P("kind", "string", "Loại kênh", enum=["text", "voice", "category"]), P("category", "string", "Tên hoặc ID category chứa kênh"),
      P("topic", "string", "Mô tả kênh text")], perm="manage_channels")
async def t_create_channel(ctx: Ctx, name: str, kind="text", category=None, topic=None):
    cat = None
    if category:
        cat, err = find_channel(ctx.guild, category, ("category",))
        if err:
            return "❌ " + err
    reason = f"AI theo yêu cầu của {ctx.asker}"
    if kind == "category":
        ch = await ctx.guild.create_category(str(name)[:100], reason=reason)
    elif kind == "voice":
        ch = await ctx.guild.create_voice_channel(str(name)[:100], category=cat, reason=reason)
    else:
        ch = await ctx.guild.create_text_channel(str(name)[:100], category=cat, topic=(topic or None), reason=reason)
    return f"✅ Đã tạo {kind} '{ch.name}' (ID {ch.id}){f' trong {cat.name}' if cat else ''}."


@tool("edit_channel", "Sửa kênh: tên, mô tả, chế độ chậm, NSFW.", [P("channel", "string", "Tên hoặc ID kênh", True),
      P("name", "string", "Tên mới"), P("topic", "string", "Mô tả mới"), P("slowmode_seconds", "integer", "Giây slowmode (0-21600)"),
      P("nsfw", "boolean", "Bật/tắt 18+")], perm="manage_channels")
async def t_edit_channel(ctx: Ctx, channel: str, name=None, topic=None, slowmode_seconds=None, nsfw=None):
    ch, err = find_channel(ctx.guild, channel)
    if err:
        return "❌ " + err
    kw = {}
    if name:
        kw["name"] = str(name)[:100]
    if topic is not None and hasattr(ch, "topic"):
        kw["topic"] = str(topic)[:1000]
    if slowmode_seconds is not None and hasattr(ch, "slowmode_delay"):
        kw["slowmode_delay"] = max(0, min(21600, int(slowmode_seconds)))
    if nsfw is not None and hasattr(ch, "nsfw"):
        kw["nsfw"] = bool(nsfw)
    if not kw:
        return "❌ Không có gì để sửa."
    await ch.edit(reason=f"AI theo yêu cầu của {ctx.asker}", **kw)
    return f"✅ Đã sửa kênh {ch.name}: " + ", ".join(f"{k} → {v}" for k, v in kw.items())


@tool("delete_channel", "Xóa kênh hoặc category (cần người dùng bấm xác nhận).", [P("channel", "string", "Tên hoặc ID", True)], perm="manage_channels")
async def t_delete_channel(ctx: Ctx, channel: str):
    ch, err = find_channel(ctx.guild, channel)
    if err:
        return "❌ " + err

    async def run():
        name = ch.name
        await ch.delete(reason=f"AI theo yêu cầu của {ctx.asker}")
        return f"✅ Đã xóa kênh {name}."
    return Confirm(f"Xóa kênh **{ch.name}** ({ch.type.name})?", "manage_channels", run, "delete_channel")


@tool("send_message", "Gửi một tin nhắn thường vào kênh (không ping everyone/role).", [P("channel", "string", "Tên hoặc ID kênh", True),
      P("content", "string", "Nội dung (tối đa 1900 ký tự)", True)], perm="manage_messages")
async def t_send_message(ctx: Ctx, channel: str, content: str):
    ch, err = find_channel(ctx.guild, channel, ("text", "news"))
    if err:
        return "❌ " + err
    await ch.send(str(content)[:1900], allowed_mentions=NO_MENTIONS)
    return f"✅ Đã gửi tin vào {ch.name}."


@tool("purge_messages", "Xóa N tin nhắn gần nhất của một kênh (cần xác nhận).", [P("channel", "string", "Tên hoặc ID kênh", True),
      P("amount", "integer", "Số tin (1-100)", True)], perm="manage_messages")
async def t_purge(ctx: Ctx, channel: str, amount: int):
    ch, err = find_channel(ctx.guild, channel, ("text", "news", "voice", "stage_voice"))
    if err:
        return "❌ " + err
    n = max(1, min(100, int(amount)))

    async def run():
        deleted = await ch.purge(limit=n)
        return f"✅ Đã xóa {len(deleted)} tin nhắn ở {ch.name}."
    return Confirm(f"Xóa **{n}** tin nhắn gần nhất ở **{ch.name}**?", "manage_messages", run, "purge_messages")


# ------------------------------------------------------------------ thanh vien
@tool("timeout_member", "Timeout (mute) một thành viên một khoảng thời gian.", [P("member", "string", "Tên, @mention hoặc ID", True),
      P("minutes", "integer", "Số phút (1-40320)", True), P("reason", "string", "Lý do")], perm="moderate_members")
async def t_timeout(ctx: Ctx, member: str, minutes: int, reason="Theo yêu cầu qua AI"):
    m, err = find_member(ctx.guild, member)
    if err:
        return "❌ " + err
    if e := hierarchy_error(ctx.guild, ctx.asker, m):
        return "❌ " + e
    mins = max(1, min(40320, int(minutes)))
    await m.timeout(timedelta(minutes=mins), reason=f"AI/{ctx.asker}: {reason}"[:500])
    await record_case(ctx.bot, ctx.guild, "Timeout", m, ctx.asker, str(reason), {"Thời hạn": f"{mins}m"})
    return f"✅ Đã timeout {m.display_name} {mins} phút."


def _punish(action: str, perm: str, verb: str):
    async def fn(ctx: Ctx, member: str, reason="Theo yêu cầu qua AI"):
        m, err = find_member(ctx.guild, member)
        if err:
            return "❌ " + err
        if e := hierarchy_error(ctx.guild, ctx.asker, m):
            return "❌ " + e

        async def run():
            if action == "Ban":
                await ctx.guild.ban(m, reason=f"AI/{ctx.asker}: {reason}"[:500])
            else:
                await m.kick(reason=f"AI/{ctx.asker}: {reason}"[:500])
            await record_case(ctx.bot, ctx.guild, action, m, ctx.asker, str(reason))
            return f"✅ Đã {verb} {m.display_name}."
        return Confirm(f"{verb.capitalize()} **{m.display_name}**? Lý do: {reason}", perm, run, f"{action.lower()}_member")
    return fn


tool("kick_member", "Kick một thành viên (cần xác nhận).", [P("member", "string", "Tên, @mention hoặc ID", True),
     P("reason", "string", "Lý do")], perm="kick_members")(_punish("Kick", "kick_members", "kick"))
tool("ban_member", "Ban một thành viên (cần xác nhận).", [P("member", "string", "Tên, @mention hoặc ID", True),
     P("reason", "string", "Lý do")], perm="ban_members")(_punish("Ban", "ban_members", "ban"))


# ------------------------------------------------------------------ chay cong cu
class ConfirmView(discord.ui.View):
    def __init__(self, ctx: Ctx, confirm: Confirm):
        super().__init__(timeout=120)
        self.ctx, self.confirm = ctx, confirm

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.asker.id:
            await interaction.response.send_message("❌ Chỉ người yêu cầu mới bấm được.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Xác nhận", style=discord.ButtonStyle.danger, emoji="✅")
    async def ok(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.defer()
        if not has_perm(self.ctx.asker, self.confirm.perm):
            return await interaction.edit_original_response(content="❌ Bạn không còn đủ quyền.", embed=None, view=None)
        try:
            out = await self.confirm.run()
        except discord.HTTPException as e:
            out = f"❌ Discord từ chối: {e.text or e}"
        await audit(self.ctx, self.confirm.audit, {}, out)
        await interaction.edit_original_response(content=out, embed=None, view=None)

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary, emoji="🚫")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="🚫 Đã hủy.", embed=None, view=None)


async def audit(ctx: Ctx, name: str, args: dict, result: str):
    e = discord.Embed(title="🤖 AI thực hiện thao tác", color=C_OK if result.startswith("✅") else C_WARN, timestamp=utcnow())
    e.add_field(name="Người yêu cầu", value=f"{ctx.asker.mention} (`{ctx.asker.id}`)")
    e.add_field(name="Công cụ", value=name)
    e.add_field(name="Kết quả", value=result[:900], inline=False)
    await send_log(ctx.bot, ctx.guild, "ch_modlog", e)


READONLY = {"list_roles", "list_channels", "member_info"}


async def run_tool(ctx: Ctx, name: str, args: dict) -> tuple[str, bool]:
    """Tra ve (ket qua cho AI, thanh cong?). Tuyet doi khong nem loi ra ngoai."""
    spec = TOOLS.get(name)
    if not spec:
        return f"❌ Không có công cụ '{name}'.", False
    if not has_perm(ctx.asker, spec["perm"]):
        label = PERM_LABELS.get(spec["perm"], "quyền quản lý")
        return f"❌ {ctx.asker.display_name} thiếu quyền Discord '{label}' để dùng chức năng này.", False
    allowed = {p[0] for p in spec["params"]}
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    try:
        out = await spec["fn"](ctx, **clean)
    except TypeError as e:
        return f"❌ Tham số không hợp lệ: {e}", False
    except discord.Forbidden:
        return "❌ Bot thiếu quyền hoặc role của bot thấp hơn mục tiêu.", False
    except discord.HTTPException as e:
        return f"❌ Discord từ chối: {e.text or e}", False
    if isinstance(out, Confirm):
        e = discord.Embed(title="⚠️ Cần xác nhận", description=out.text, color=C_WARN)
        try:
            await ctx.channel.send(content=ctx.asker.mention, embed=e, view=ConfirmView(ctx, out),
                                   allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            return "❌ Không gửi được nút xác nhận.", False
        return "ĐÃ GỬI nút xác nhận cho người dùng; thao tác chưa thực hiện cho đến khi họ bấm. Hãy báo họ bấm nút.", True
    if name not in READONLY:
        await audit(ctx, name, clean, out)
    return out, not out.startswith("❌")
