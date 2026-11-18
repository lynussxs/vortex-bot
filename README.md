# Arcadia Bot

Bot quản lý server Discord: lệnh slash (`/`), kiểm duyệt, level/XP, chào mừng, nhật ký, AutoMod và AI (Claude).
AI **chỉ trả lời khi có người @tên bot** (hoặc dùng `/hoi`).

## Chức năng

| Module | Lệnh / hành vi |
|---|---|
| Kiểm duyệt | `/ban` `/unban` `/kick` `/timeout` `/untimeout` `/warn` `/warnings` `/clearwarns` `/purge` `/slowmode` `/lock` `/unlock`. Mỗi hành động ghi case, log vào kênh staff và đăng bản ghi gọn (không chép nội dung tin nhắn) vào kênh xử phạt. Đủ 3 cảnh cáo thì tự timeout 60 phút. |
| Level/XP | XP theo tin nhắn (cooldown 60s), `/rank` `/leaderboard`, `/levelrole add/remove/list` (role thưởng), `/xp add/set`, `/levels` bật/tắt |
| Chào mừng | `/welcome message/goodbye/test`, `/autorole set/clear` (biến: `{user} {name} {server} {count}`) |
| Nhật ký | tin nhắn xóa/sửa, vào/rời, đổi role/nickname, voice, tạo/xóa kênh/role, ban/unban |
| AutoMod | chống spam, chặn link mời, chống mention hàng loạt, từ cấm, chống raid. `/automod status/toggle`, `/automod word add/remove/list`. Staff được miễn. |
| Tiện ích | `/help` `/ping` `/serverinfo` `/userinfo` `/avatar` `/poll` `/embed` `/announce` |
| AI | @bot hoặc `/hoi`; `/tomtat`; admin: `/ai prompt set/load/show/reset`, `/ai kb add/list/show/remove`, `/ai channels add/remove/all`, `/ai automod`, `/ai toggle`, `/ai status` |
| Cấu hình | `/setup auto` (tự dò kênh theo tên), `/setup channel`, `/setup role`, `/setup show`, `/setup congkhai` |

## Gắn prompt / kiến thức cho AI
AI biết gì về server của bạn từ 3 nguồn, cộng dồn lại:
1. **`knowledge.md`** trong repo (đã điền sẵn cấu trúc kênh/role của Arcadia.vn; sửa mục `(ĐIỀN THÊM)` rồi push lên GitHub, Railway tự deploy).
2. **`/ai prompt set`**: hộp nhập chỉ dẫn riêng (tối đa 4000 ký tự), hoặc `/ai prompt load` để nạp từ file `.txt/.md`. Dùng cho giọng điệu, luật, thông tin dài. Đổi là áp dụng ngay.
3. **`/ai kb add`**: kho kiến thức dạng mục nhỏ (vd "Cách nhận role màu", "Quyền lợi VIP"). Dễ thêm/xóa từng mục.

AI cũng tự biết tên server, số thành viên và danh sách kênh mà `@everyone` nhìn thấy (kênh staff không bị lộ).
Ví dụ hỏi: _"@bot server mình có những kênh game nào?"_ hoặc _"@bot làm sao nhận role màu?"_.

## Chuẩn bị
1. **Developer Portal → Bot**: bật **Server Members Intent** và **Message Content Intent**.
2. **Mời bot** vào server với quyền: Manage Roles, Manage Channels, Kick/Ban Members, Moderate Members, Manage Messages, View Audit Log, View Channels, Send Messages, Embed Links, Attach Files, Add Reactions, Read Message History, Use External Emojis (scope `bot` và `applications.commands`). Link mẫu (thay `CLIENT_ID`):
   `https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot%20applications.commands&permissions=1374658358486`
3. **Kéo role của bot lên cao** trong Server Settings → Roles (cao hơn các role cần quản lý, thấp hơn role Owner).
4. Lấy **API key Claude** tại console.anthropic.com (nếu không có thì mọi thứ vẫn chạy, chỉ AI bị tắt).

## Deploy lên Railway
1. Đẩy thư mục này lên một repo GitHub (**private**).
2. Railway → New Project → Deploy from GitHub repo → chọn repo.
3. Tab **Variables** thêm: `DISCORD_TOKEN`, `GUILD_ID` (ID server của bạn, để lệnh slash hiện ngay), `ANTHROPIC_API_KEY`, `DB_PATH=/data/bot.db`.
4. Thêm **Volume** gắn vào đường dẫn `/data` (**bắt buộc**, nếu không dữ liệu XP/cảnh cáo mất sau mỗi lần deploy).
5. Nếu Railway không tự nhận lệnh chạy: Settings → Start Command = `python main.py`.
6. Xem tab Logs, thấy `Đã đồng bộ N lệnh slash` và `Bot sẵn sàng` là xong.
7. Trong Discord chạy `/setup auto` rồi `/setup show` kiểm tra, sau đó `/ai status`.

> Giao diện Railway có thể hơi khác mô tả trên. **Token và API key chỉ đặt trong Variables**, không ghi vào code, không dán lên chat.
> Nếu đã từng đồng bộ lệnh toàn cầu rồi chuyển sang `GUILD_ID` (hoặc ngược lại) thì lệnh có thể hiện đôi; xóa `GUILD_ID` hoặc reset lệnh trong Developer Portal để dọn.

## Chạy thử trên máy (Fedora)
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DISCORD_TOKEN=...   GUILD_ID=...   ANTHROPIC_API_KEY=...
python3 main.py
```

## Tiết kiệm chi phí AI
- Mặc định dùng model nhỏ (`claude-haiku-5-5`, đổi bằng biến `AI_MODEL`). Phần prompt cố định được bật prompt caching.
- Mỗi người tối đa `AI_USER_HOURLY` (30) câu/giờ, cách nhau 6 giây. AI kiểm duyệt tối đa `AI_MOD_HOURLY` (60) lần/giờ/server.
- Chỉ **một số ít tin nghi ngờ** (mẫu lừa đảo, link rút gọn...) mới được gửi cho AI, không gửi mọi tin nhắn.
- Dùng `/ai channels add` để giới hạn AI chỉ trả lời ở vài kênh.

## Lưu ý
- Arcane/ProBot/Sapphire đang chạy cùng: hãy tắt tính năng trùng (đặc biệt XP/level, chào mừng, log) của bot cũ để không bị báo hai lần.
- Nút Duyệt/Bỏ qua của AI chỉ hoạt động trong 1 giờ và mất khi bot khởi động lại; staff vẫn xử lý tay bằng `/timeout`, `/purge`.
- Bot không bao giờ tự ban người dùng.
