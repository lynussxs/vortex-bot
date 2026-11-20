"""/embed: gui/sua embed bang JSON (kieu Discohook), nut link, va panel nhan role (menu/nut) ben vung qua restart."""
import json
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.agent import find_role
from core.util import utcnow

MAX_EMBEDS, MAX_TOTAL = 10, 6000

EXAMPLE = """{
  "content": "",
  "embeds": [
    {
      "title": "🎨 CHỌN MÀU TÊN",
      "description": "Chọn một màu bên dưới!\\n\\n🩷 **Hồng**\\n🟣 **Tím**",
      "color": "#B197FC",
      "fields": [{"name": "📌 Cách dùng", "value": "Bấm menu bên dưới.", "inline": false}],
      "footer": {"text": "Arcadia.vn"}
    }
  ],
  "buttons": [{"label": "Luật server", "url": "https://discord.com"}],
  "roles": {
    "type": "menu",
    "exclusive": true,
    "placeholder": "Chọn màu tên của bạn",
    "options": [
      {"label": "Hồng", "emoji": "🩷", "role": "Hồng", "description": "Tên màu hồng"},
      {"label": "Tím", "emoji": "🟣", "role": "Tím"}
    ]
  }
}"""


# ---------------------------------------------------------------- phan tich JSON (thuan)
def _color(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", v.strip()):
        return int(v.strip().lstrip("#"), 16)
    raise ValueError(f"Màu không hợp lệ: {v!r} (dùng số hoặc mã hex như #B197FC).")


def _norm_embed(d: dict) -> discord.Embed:
    e = dict(d)
    if "color" in e or "colour" in e:
        e["color"] = _color(e.pop("colour", None) if "colour" in e else e["color"])
    if e.get("timestamp") == "now":
        e["timestamp"] = utcnow().isoformat()
    for k in ("image", "thumbnail"):
        if isinstance(e.get(k), str):
            e[k] = {"url": e[k]}
    if isinstance(e.get("footer"), str):
        e["footer"] = {"text": e["footer"]}
    if isinstance(e.get("author"), str):
        e["author"] = {"name": e["author"]}
    fields = e.get("fields") or []
    if len(fields) > 25:
        raise ValueError("Embed chỉ được tối đa 25 field.")
    e["fields"] = [{"name": str(f.get("name", "\u200b"))[:256], "value": str(f.get("value", "\u200b"))[:1024],
                    "inline": bool(f.get("inline", False))} for f in fields if isinstance(f, dict)]
    if len(str(e.get("title", ""))) > 256:
        raise ValueError("Tiêu đề tối đa 256 ký tự.")
    if len(str(e.get("description", ""))) > 4096:
        raise ValueError("Mô tả tối đa 4096 ký tự.")
    return discord.Embed.from_dict(e)


def parse_payload(raw: str) -> dict:
    """JSON (hoac code block) -> {'content', 'embeds', 'buttons', 'roles'}. Loi -> ValueError (tieng Viet)."""
    text = raw.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if m:
        text = m.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON sai cú pháp: {e.msg} (dòng {e.lineno}, cột {e.colno}).") from None
    if isinstance(data, list):
        data = {"embeds": data}
    elif isinstance(data, dict) and "embeds" not in data and "embed" not in data and any(
            k in data for k in ("title", "description", "fields", "image", "thumbnail", "author", "footer", "color")):
        data = {"embeds": [data]}
    if not isinstance(data, dict):
        raise ValueError("JSON phải là một đối tượng {...} hoặc danh sách embed.")
    raw_embeds = data.get("embeds") or ([data["embed"]] if data.get("embed") else [])
    if len(raw_embeds) > MAX_EMBEDS:
        raise ValueError(f"Tối đa {MAX_EMBEDS} embed trong một tin.")
    embeds = [_norm_embed(x) for x in raw_embeds if isinstance(x, dict)]
    if sum(len(e) for e in embeds) > MAX_TOTAL:
        raise ValueError(f"Tổng số ký tự các embed vượt {MAX_TOTAL}.")
    content = str(data.get("content") or "")[:2000] or None
    if not content and not embeds:
        raise ValueError("JSON không có nội dung nào để gửi (cần `content` hoặc `embeds`).")
    return {"content": content, "embeds": embeds, "buttons": data.get("buttons") or [], "roles": data.get("roles")}


# ---------------------------------------------------------------- panel role
def plan_button(current: set, role_id: int, panel: set, exclusive: bool):
    """Bam nut: bat/tat 1 role. Exclusive thi go cac role khac cua panel."""
    if role_id in current:
        return set(), {role_id}
    return {role_id}, ((panel & current) - {role_id} if exclusive else set())


def plan_menu(current: set, selected: set, panel: set):
    """Chon trong menu: them role duoc chon, go role cua panel bi bo chon."""
    return selected - current, (panel & current) - selected


def panel_role_ids(message: discord.Message) -> set:
    ids = set()
    for row in message.components:
        for c in getattr(row, "children", []):
            cid = getattr(c, "custom_id", None) or ""
            if cid.startswith("rp:b:"):
                ids.add(int(cid.split(":")[2]))
            for o in getattr(c, "options", []) or []:
                if cid.startswith("rp:m:") and str(o.value).isdigit() and int(o.value) > 0:
                    ids.add(int(o.value))
    return ids


async def apply_roles(interaction: discord.Interaction, to_add: set, to_remove: set):
    g, member = interaction.guild, interaction.user
    add = [r for r in (g.get_role(i) for i in to_add) if r]
    rem = [r for r in (g.get_role(i) for i in to_remove) if r]
    try:
        if add:
            await member.add_roles(*add, reason="Role panel")
        if rem:
            await member.remove_roles(*rem, reason="Role panel")
    except discord.HTTPException:
        return await interaction.response.send_message(
            "❌ Bot không gán được role này (role của bot phải nằm cao hơn role cần gán).", ephemeral=True)
    lines = [f"✅ Đã nhận: {', '.join(r.mention for r in add)}"] if add else []
    if rem:
        lines.append(f"➖ Đã gỡ: {', '.join(r.mention for r in rem)}")
    await interaction.response.send_message("\n".join(lines) or "Không có thay đổi.", ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())


class RoleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"rp:b:(?P<role>[0-9]+):(?P<ex>[01])"):
    def __init__(self, role_id: int, exclusive: bool = False, label=None, emoji=None):
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary,
                                           custom_id=f"rp:b:{role_id}:{int(exclusive)}"))
        self.role_id, self.exclusive = role_id, exclusive

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["role"]), match["ex"] == "1")

    async def callback(self, interaction: discord.Interaction):
        current = {r.id for r in interaction.user.roles}
        add, rem = plan_button(current, self.role_id, panel_role_ids(interaction.message), self.exclusive)
        await apply_roles(interaction, add, rem)


class RoleMenu(discord.ui.DynamicItem[discord.ui.Select], template=r"rp:m:(?P<ex>[01])"):
    def __init__(self, exclusive: bool = False, options=None, placeholder=None):
        options = options or [discord.SelectOption(label="…", value="0")]
        super().__init__(discord.ui.Select(custom_id=f"rp:m:{int(exclusive)}", placeholder=placeholder, options=options,
                                           min_values=0, max_values=1 if exclusive else len(options)))
        self.exclusive = exclusive

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["ex"] == "1")

    async def callback(self, interaction: discord.Interaction):
        selected = {int(v) for v in interaction.data.get("values", []) if str(v).isdigit()}
        current = {r.id for r in interaction.user.roles}
        add, rem = plan_menu(current, selected, panel_role_ids(interaction.message))
        await apply_roles(interaction, add, rem)


def build_view(guild: discord.Guild, payload: dict):
    """Tao View tu 'buttons' (nut link) va 'roles' (panel). Tra ve (view|None, loi|None)."""
    items = []
    for b in payload["buttons"][:5]:
        if not isinstance(b, dict) or not str(b.get("url", "")).startswith(("http://", "https://")):
            return None, "Mỗi nút trong `buttons` cần `url` bắt đầu bằng http(s)://"
        items.append(discord.ui.Button(label=str(b.get("label", "Mở"))[:80], url=b["url"],
                                       emoji=b.get("emoji") or None))
    spec = payload["roles"]
    if spec:
        opts = spec.get("options") or []
        if not 1 <= len(opts) <= 25:
            return None, "`roles.options` cần từ 1 đến 25 mục."
        exclusive = bool(spec.get("exclusive", False))
        resolved = []
        for o in opts:
            role, err = find_role(guild, o.get("role", ""))
            if err:
                return None, err
            if role.is_default() or role >= guild.me.top_role:
                return None, f"Role '{role.name}' cao hơn role của bot (hoặc là @everyone) nên bot không gán được."
            resolved.append((o, role))
        if spec.get("type", "menu") == "buttons":
            if len(resolved) > 20:
                return None, "Dạng `buttons` tối đa 20 nút."
            items += [RoleButton(r.id, exclusive, str(o.get("label") or r.name)[:80], o.get("emoji") or None)
                      for o, r in resolved]
        else:
            options = [discord.SelectOption(label=str(o.get("label") or r.name)[:100], value=str(r.id),
                                            emoji=o.get("emoji") or None,
                                            description=(str(o["description"])[:100] if o.get("description") else None))
                       for o, r in resolved]
            items.append(RoleMenu(exclusive, options, str(spec.get("placeholder") or "Chọn role")[:150]))
    if not items:
        return None, None
    view = discord.ui.View(timeout=None)
    for it in items:
        view.add_item(it)
    return view, None


# ---------------------------------------------------------------- lenh
class JSONModal(discord.ui.Modal, title="Nhập JSON embed"):
    code = discord.ui.TextInput(label="JSON (xem /embed example)", style=discord.TextStyle.paragraph,
                                max_length=4000, required=True)

    def __init__(self, cog, channel, edit_message=None, prefill=""):
        super().__init__()
        self.cog, self.channel, self.edit_message = cog, channel, edit_message
        self.code.default = prefill[:4000]

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.deliver(interaction, self.channel, self.code.value, self.edit_message)


class EmbedTools(commands.Cog):
    embed = app_commands.Group(name="embed", description="Gửi/sửa embed bằng JSON", guild_only=True,
                               default_permissions=discord.Permissions(manage_messages=True))

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(RoleButton, RoleMenu)

    async def deliver(self, interaction: discord.Interaction, channel, raw: str, edit_message=None):
        try:
            payload = parse_payload(raw)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        perms = interaction.user.guild_permissions
        if payload["roles"] and not perms.manage_roles:
            return await interaction.response.send_message("❌ Panel nhận role cần quyền Manage Roles.", ephemeral=True)
        view, err = build_view(interaction.guild, payload)
        if err:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        mentions = discord.AllowedMentions(everyone=perms.mention_everyone, roles=perms.mention_everyone, users=True)
        kw = {"content": payload["content"], "embeds": payload["embeds"], "allowed_mentions": mentions}
        try:
            if edit_message:
                if view is not None:
                    kw["view"] = view
                await edit_message.edit(**kw)
                where = edit_message.jump_url
            else:
                sent = await channel.send(view=view, **kw) if view is not None else await channel.send(**kw)
                where = sent.jump_url
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Bot không có quyền gửi/sửa ở kênh đó.", ephemeral=True)
        except discord.HTTPException as e:
            return await interaction.response.send_message(f"❌ Discord từ chối: {e.text or e}", ephemeral=True)
        await interaction.response.send_message(f"✅ {'Đã sửa' if edit_message else 'Đã gửi'}: {where}", ephemeral=True)

    @embed.command(name="send", description="Gửi embed: mở hộp nhập JSON")
    @app_commands.describe(kenh="Kênh gửi (mặc định kênh hiện tại)")
    async def send(self, interaction: discord.Interaction, kenh: Optional[discord.TextChannel] = None):
        await interaction.response.send_modal(JSONModal(self, kenh or interaction.channel))

    @embed.command(name="file", description="Gửi embed từ file .json (cho JSON dài hơn 4000 ký tự)")
    @app_commands.describe(file="File .json hoặc .txt", kenh="Kênh gửi (mặc định kênh hiện tại)")
    async def file(self, interaction: discord.Interaction, file: discord.Attachment,
                   kenh: Optional[discord.TextChannel] = None):
        if file.size > 100_000:
            return await interaction.response.send_message("❌ File quá lớn (tối đa 100KB).", ephemeral=True)
        try:
            raw = (await file.read()).decode("utf-8")
        except UnicodeDecodeError:
            return await interaction.response.send_message("❌ File phải là văn bản UTF-8.", ephemeral=True)
        await self.deliver(interaction, kenh or interaction.channel, raw)

    @embed.command(name="edit", description="Sửa một tin nhắn embed của bot bằng JSON")
    @app_commands.describe(message_id="ID tin nhắn của bot", kenh="Kênh chứa tin (mặc định kênh hiện tại)")
    async def edit(self, interaction: discord.Interaction, message_id: str, kenh: Optional[discord.TextChannel] = None):
        channel = kenh or interaction.channel
        try:
            msg = await channel.fetch_message(int(message_id.strip()))
        except (ValueError, discord.NotFound):
            return await interaction.response.send_message("❌ Không tìm thấy tin nhắn (kiểm tra ID và kênh).", ephemeral=True)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Bot không đọc được tin nhắn đó.", ephemeral=True)
        if msg.author.id != self.bot.user.id:
            return await interaction.response.send_message("❌ Chỉ sửa được tin nhắn do bot gửi.", ephemeral=True)
        current = json.dumps({"content": msg.content, "embeds": [e.to_dict() for e in msg.embeds]},
                             ensure_ascii=False, indent=2)
        await interaction.response.send_modal(JSONModal(self, channel, msg, current))

    @embed.command(name="example", description="Xem JSON mẫu để copy")
    async def example(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "**JSON mẫu** (có thể dùng dạng Discohook: chỉ cần `embeds`). `buttons` là nút link, `roles` là panel nhận role "
            "(`type`: `menu` hoặc `buttons`, `exclusive`: chỉ chọn một).\n```json\n" + EXAMPLE + "\n```", ephemeral=True)

    @embed.command(name="simple", description="Gửi nhanh embed đơn giản (không cần JSON)")
    @app_commands.describe(tieu_de="Tiêu đề", noi_dung="Nội dung (\\n để xuống dòng)", mau="Màu hex, ví dụ B197FC",
                           kenh="Kênh gửi (mặc định kênh hiện tại)")
    async def simple(self, interaction: discord.Interaction, tieu_de: app_commands.Range[str, 1, 256],
                     noi_dung: app_commands.Range[str, 1, 3000], mau: str = "5B8DEF",
                     kenh: Optional[discord.TextChannel] = None):
        try:
            color = _color("#" + mau.lstrip("#"))
        except ValueError:
            return await interaction.response.send_message("❌ Màu không hợp lệ (ví dụ `B197FC`).", ephemeral=True)
        e = discord.Embed(title=tieu_de, description=noi_dung.replace("\\n", "\n"), color=color)
        try:
            await (kenh or interaction.channel).send(embed=e)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Bot không gửi được vào kênh đó.", ephemeral=True)
        await interaction.response.send_message("✅ Đã gửi.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(EmbedTools(bot))
