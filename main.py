import os
import discord
from discord.ext import commands

# 1. Cấu hình Intents (Quyền của bot)
# Intents.default() đủ cho các tính năng cơ bản; thêm message_content và members để quản lý server tốt hơn
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# 2. Khởi tạo bot với tiền tố (prefix) lệnh là dấu gạch chéo hoặc dấu chấm (ví dụ: !help)
# Bạn cũng có thể dùng slash commands (app_commands) sau khi bot online
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"========================================")
    print(f" [OK] Bot da dang nhap thanh cong!")
    print(f" [INFO] Ten bot: {bot.user.name} (ID: {bot.user.id})")
    print(f" [INFO] Dang hoat dong tren {len(bot.guilds)} server.")
    print(f"========================================")
    
    # Đặt trạng thái hoạt động cho bot (Custom Status hoặc Playing)
    activity = discord.Activity(type=discord.ActivityType.watching, name="over Arcadia.vn 🛡️")
    await bot.change_presence(status=discord.Status.online, activity=activity)

# Lệnh kiểm tra bot sống hay chết (Ping test)
@bot.command(name="ping")
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Độ trễ hệ thống: `{latency}ms`")

# 3. Khu vực để bạn viết các tính năng mới vào ngày mai (Cơ chế Cog hoặc viết trực tiếp)
# Ví dụ: Ngày mai bạn có thể thêm các lệnh quản lý, tự động gán role, v.v.

if __name__ == "__main__":
    # Thay 'YOUR_BOT_TOKEN_HERE' bằng Token thật của bot Vortex lấy từ Discord Developer Portal
    TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("[!] Hay thay Token that cua bot vao bien TOKEN truoc khi chay!")
    else:
        bot.run(TOKEN)
