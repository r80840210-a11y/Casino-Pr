import asyncio
import os
import sqlite3
import aiohttp
import uvicorn
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан!")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ---------- SQLite ----------
db = sqlite3.connect("osint.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS name_history(
    user_id INTEGER, name TEXT, username TEXT, ts TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS known_chats(
    chat_id INTEGER PRIMARY KEY, title TEXT)""")
db.commit()

def save_name(uid, name, username):
    # Проверяем, изменилось ли имя, чтобы не спамить одинаковыми записями
    cur = db.execute("SELECT name, username FROM name_history WHERE user_id=? ORDER BY ts DESC LIMIT 1", (uid,))
    last = cur.fetchone()
    if last and last[0] == name and last[1] == (username or ""):
        return # Имя не изменилось, не записываем
    
    db.execute("INSERT INTO name_history VALUES(?,?,?,?)",
               (uid, name, username or "", datetime.now().isoformat()))
    db.commit()

def get_name_history(uid):
    cur = db.execute(
        "SELECT name, username, ts FROM name_history WHERE user_id=? ORDER BY ts",
        (uid,))
    return cur.fetchall()

# ---------- Блоки отчёта ----------
async def profile_block(user) -> str:
    try:
        photos = await bot.get_user_profile_photos(user_id=user.id, limit=1)
        photo_count = photos.total_count
    except Exception:
        photo_count = 0
    return (
        "👤 <b>ПРОФИЛЬ</b>\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📛 Имя: {user.first_name} {user.last_name or ''}\n"
        f"🔗 Username: {'@'+user.username if user.username else '—'}\n"
        f"🌐 Язык: {user.language_code or '—'}\n"
        f"💎 Premium: {'Да' if user.is_premium else 'Нет'}\n"
        f"🖼 Фото: {photo_count}\n"
    )

def history_block(uid) -> str:
    rows = get_name_history(uid)
    if len(rows) <= 1:
        return "📜 <b>ИСТОРИЯ ИМЁН</b>\nПока не менялось (бот запоминает при каждом обращении).\n"
    text = "📜 <b>ИСТОРИЯ ИМЁН</b>\n"
    for name, uname, ts in rows[-10:]:
        text += f"• {ts[:16]} — {name} {('@'+uname) if uname else ''}\n"
    return text

PLATFORMS = {
    "GitHub": "https://github.com/{}", "Instagram": "https://instagram.com/{}",
    "TikTok": "https://tiktok.com/@{}", "Twitter/X": "https://x.com/{}",
    "YouTube": "https://youtube.com/@{}", "Reddit": "https://reddit.com/user/{}",
    "Steam": "https://steamcommunity.com/id/{}", "Pinterest": "https://pinterest.com/{}",
    "Twitch": "https://twitch.tv/{}", "VK": "https://vk.com/{}",
    "Habr": "https://habr.com/ru/users/{}/", "Flickr": "https://flickr.com/people/{}",
}

async def osint_block(username: str) -> str:
    if not username:
        return "🔎 <b>USERNAME-OSINT</b>\nUsername не указан.\n"
    text = f"🔎 <b>USERNAME-OSINT: @{username}</b>\n"
    timeout = aiohttp.ClientTimeout(total=6)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        for name, url_tpl in PLATFORMS.items():
            url = url_tpl.format(username)
            try:
                async with s.head(url, allow_redirects=True) as r:
                    status = "✅" if r.status == 200 else "❌"
                    text += f"{status} {name}: {url}\n"
            except Exception:
                text += f"⚠️ {name}: ошибка\n"
    return text

async def build_report(user) -> str:
    save_name(user.id, f"{user.first_name} {user.last_name or ''}".strip(), user.username)
    report = await profile_block(user)
    report += "\n" + history_block(user.id)
    report += "\n" + await osint_block(user.username)
    return report

# ---------- Хендлеры ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    report = await build_report(message.from_user)
    await message.answer(report + "\n\n<i>💡 Чтобы пробить другого человека, отправь мне его @username (например: @durov)</i>")

# ---------- ПОИСК ПО USERNAME БЕЗ ГРУПП ----------
@dp.message(F.text.startswith("@") | F.text.startswith("https://t.me/") | F.text.startswith("t.me/"))
async def search_by_username(message: Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    
    # Очищаем ввод, чтобы получить чистый юзернейм
    raw = message.text.replace("https://t.me/", "").replace("t.me/", "").replace("@", "").strip()
    
    try:
        # Запрашиваем инфу о юзере через Telegram API
        chat = await bot.get_chat(f"@{raw}")
        
        # Бот может получить полную инфу только если юзер есть в базе Telegram API
        if chat.type != "private":
            await message.answer("❌ Это не пользователь, а канал или группа.")
            return

        save_name(chat.id, f"{chat.first_name or ''} {chat.last_name or ''}".strip(), chat.username)
        
        report = (
            f"👤 <b>ПРОФИЛЬ (по нику)</b>\n"
            f"🆔 ID: <code>{chat.id}</code>\n"
            f"📛 Имя: {chat.first_name} {chat.last_name or ''}\n"
            f"🔗 Username: @{chat.username}\n"
            f"🖼 Фото: {'Есть' if chat.photo else 'Нет'}\n"
            f"💎 Premium: {'Да' if getattr(chat, 'is_premium', False) else 'Нет'}\n"
        )
        report += "\n" + history_block(chat.id)
        report += "\n" + await osint_block(chat.username)
        
        await message.answer(report)
        
    except Exception as e:
        await message.answer(f"❌ Не удалось найти пользователя @{raw}.\nОшибка: <code>{e}</code>")

@dp.message(Command("target"))
async def cmd_target(message: Message):
    if not message.reply_to_message:
        await message.answer("Ответьте командой /target на сообщение нужного пользователя.")
        return
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    report = await build_report(message.reply_to_message.from_user)
    await message.answer(report)

# ---------- FastAPI ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(dp.start_polling(bot))
    yield
    await bot.session.close()

web = FastAPI(lifespan=lifespan)

@web.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(web, host="0.0.0.0", port=PORT)
