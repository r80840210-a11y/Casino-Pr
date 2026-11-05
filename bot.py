import asyncio
import os
import sqlite3
import aiohttp
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ChatAction
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ---------- Конфиг из переменных окружения ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Добавьте переменную окружения BOT_TOKEN.")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ---------- SQLite ----------
db = sqlite3.connect("osint.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS name_history(
    user_id INTEGER, name TEXT, username TEXT, ts TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS reports(
    user_id INTEGER, report TEXT, ts TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS known_chats(
    chat_id INTEGER PRIMARY KEY, title TEXT)""")
db.commit()


def save_name(uid, name, username):
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
        f"🤖 Бот: {'Да' if user.is_bot else 'Нет'}\n"
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


async def common_groups_block(user_id: int) -> str:
    cur = db.execute("SELECT chat_id, title FROM known_chats")
    chats = cur.fetchall()
    if not chats:
        return ("👥 <b>ОБЩИЕ ГРУППЫ</b>\n"
                "Нет данных. Добавьте бота в группы — он запомнит их.\n")
    found = []
    for chat_id, title in chats:
        try:
            m = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if m.status in ("member", "administrator", "creator"):
                role = {"member": "участник",
                        "administrator": "админ",
                        "creator": "владелец"}[m.status]
                found.append(f"• {title} (<code>{chat_id}</code>) — {role}")
        except Exception:
            continue
    if not found:
        return "👥 <b>ОБЩИЕ ГРУППЫ</b>\nНе найден ни в одной известной боту группе.\n"
    return "👥 <b>ОБЩИЕ ГРУППЫ</b>\n" + "\n".join(found) + "\n"


PLATFORMS = {
    "GitHub": "https://github.com/{}",
    "Instagram": "https://instagram.com/{}",
    "TikTok": "https://tiktok.com/@{}",
    "Twitter/X": "https://x.com/{}",
    "YouTube": "https://youtube.com/@{}",
    "Reddit": "https://reddit.com/user/{}",
    "Steam": "https://steamcommunity.com/id/{}",
    "Pinterest": "https://pinterest.com/{}",
    "Twitch": "https://twitch.tv/{}",
    "VK": "https://vk.com/{}",
    "Habr": "https://habr.com/ru/users/{}/",
    "Flickr": "https://flickr.com/people/{}",
}


async def osint_block(username: str) -> str:
    if not username:
        return "🔎 <b>USERNAME-OSINT</b>\nUsername не указан — проверка невозможна.\n"
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


async def avatar_block(user_id: int) -> str:
    try:
        photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
        if photos.total_count == 0:
            return "🖼 <b>АВАТАР</b>\nФото профиля нет.\n"
        file_id = photos.photos[0][-1].file_id
        file = await bot.get_file(file_id)
        path = f"/tmp/avatar_{user_id}.jpg"
        await bot.download_file(file.file_path, path)
        return (
            "🖼 <b>АВАТАР</b>\n"
            f"Скачан: <code>{path}</code>\n"
            "Для поиска по лицу:\n"
            "• https://yandex.ru/images\n"
            "• https://lens.google.com\n"
            "• https://pimeyes.com (платно)\n"
        )
    except Exception as e:
        return f"🖼 <b>АВАТАР</b>\nОшибка: {e}\n"


async def build_report(user) -> str:
    save_name(user.id, f"{user.first_name} {user.last_name or ''}".strip(), user.username)
    report = await profile_block(user)
    report += "\n" + history_block(user.id)
    report += "\n" + await common_groups_block(user.id)
    report += "\n" + await osint_block(user.username)
    report += "\n" + await avatar_block(user.id)
    db.execute("INSERT INTO reports VALUES(?,?,?)",
               (user.id, report, datetime.now().isoformat()))
    db.commit()
    return report


# ---------- Хендлеры ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    report = await build_report(message.from_user)
    await message.answer(report)


@dp.message(Command("report"))
async def cmd_report(message: Message):
    await cmd_start(message)


@dp.message(Command("target"))
async def cmd_target(message: Message):
    if not message.reply_to_message:
        await message.answer("Ответьте командой /target на сообщение нужного пользователя.")
        return
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    report = await build_report(message.reply_to_message.from_user)
    await message.answer(report)


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def remember_chat(message: Message):
    db.execute("INSERT OR REPLACE INTO known_chats VALUES(?,?)",
               (message.chat.id, message.chat.title or "без названия"))
    db.commit()


# ---------- FastAPI healthcheck для Render ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(dp.start_polling(bot))
    yield
    await bot.session.close()


web = FastAPI(lifespan=lifespan)


@web.get("/")
async def root():
    return {"status": "ok", "service": "rocket-osint-bot"}


@web.get("/health")
async def health():
    return {"status": "healthy"}


# ---------- Точка входа ----------
if __name__ == "__main__":
    uvicorn.run(web, host="0.0.0.0", port=PORT)
