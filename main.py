import os
import discord
from discord.ext import commands

# Cấu hình Intents (Quyền của bot)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Khởi tạo bot với prefix lệnh là dấu '!'
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print("========================================")
    print(f" [OK] Bot da dang nhap thanh cong!")
    print(f" [INFO] Ten bot: {bot.user.name} (ID: {bot.user.id})")
    print(f" [INFO] Dang hoat dong tren {len(bot.guilds)} server.")
    print("========================================")
    
    # Đặt trạng thái hoạt động hiển thị cho bot
    activity = discord.Activity(type=discord.ActivityType.watching, name="over Arcadia.vn 🛡️")
    await bot.change_presence(status=discord.Status.online, activity=activity)

# Lệnh kiểm tra độ trễ (Ping test)
@bot.command(name="ping")
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Độ trễ hệ thống: `{latency}ms`")

if __name__ == "__main__":
    # Lấy token bảo mật từ biến môi trường của hệ thống (Railway)
    TOKEN = os.getenv("DISCORD_TOKEN")
    
    if not TOKEN:
        print("[!] Loi: Chua thiet lap bien moi truong DISCORD_TOKEN!")
    else:
        bot.run(TOKEN)
