import asyncio
import logging
import os
import socket
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

# Твой токен уже прописан прямо здесь, ошибки с переменными больше не будет
TOKEN = "1780243383:8pd9P5LHXvqwS1Fb6Lb1M4H52cPh5IN3vXi"

SERVER_IP = "67.211.221.152"
SERVER_PORT = 8888

bot = Bot(token=TOKEN)
dp = Dispatcher()

def check_server_status(ip, port, timeout=3):
    """Проверяет доступность порта кастомного сервера"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error):
        return False

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот-монитор кастомного сервера.\n"
        "Используй /status для проверки связи с сервером."
    )

@dp.message(Command("status"))
async def cmd_status(message: Message):
    msg = await message.answer("🔍 Проверяю статус сервера...")
    is_online = await asyncio.to_thread(check_server_status, SERVER_IP, SERVER_PORT)
    
    if is_online:
        text = (
            f"🟢 **Сервер ОНЛАЙН!**\n\n"
            f"🌐 IP: `{SERVER_IP}:{SERVER_PORT}`\n"
            f"✨ Соединение стабильное."
        )
    else:
        text = (
            f"🔴 **Сервер ОФФЛАЙН / Недоступен**\n\n"
            f"🌐 IP: `{SERVER_IP}:{SERVER_PORT}`\n"
            f"⚠️ Сервер выключен или недоступен по сети."
        )
    await msg.edit_text(text, parse_mode="Markdown")

# Заглушка веб-сервера для Render (чтобы бесплатный хостинг не усыплял бота)
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    logging.basicConfig(level=logging.INFO)
    await asyncio.gather(
        web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
