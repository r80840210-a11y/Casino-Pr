import os
import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
import random

# Логирование
logging.basicConfig(level=logging.INFO)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CUSTOM_API_URL = os.getenv("TELEGRAM_API_URL", "http://67.211.221.152:8888")
PORT = int(os.getenv("PORT", "8080"))
INITIAL_ADMIN_ID = 1780243264
DB_NAME = "casino_bot.db"

# Инициализация бота с поддержкой Кастомного Сервера Телеграм
session = AiohttpSession(
    api=TelegramAPIServer.from_base(CUSTOM_API_URL, is_local=True)
)
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# --- FSM Состояния ---
class GameStates(StatesGroup):
    waiting_for_bet = State()

class WithdrawStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_address = State()

class PromoStates(StatesGroup):
    waiting_for_code = State()

class AdminStates(StatesGroup):
    waiting_for_add_admin_id = State()
    waiting_for_del_admin = State()
    waiting_for_ban_user = State()
    waiting_for_unban_user = State()
    waiting_for_give_stars_user = State()
    waiting_for_give_stars_amount = State()
    waiting_for_take_stars_user = State()
    waiting_for_take_stars_amount = State()
    waiting_for_broadcast = State()
    waiting_for_promo_name = State()
    waiting_for_promo_activations = State()
    waiting_for_promo_stars = State()
    waiting_for_min_withdraw = State()

# --- Работа с Базой Данных ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Пользователи
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0
            )
        ''')
        # Админы с ролями (super / junior)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                role TEXT DEFAULT 'junior'
            )
        ''')
        # Заявки на вывод
        await db.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                address TEXT,
                status TEXT DEFAULT 'pending'
            )
        ''')
        # Промокоды
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                activations_left INTEGER,
                stars_reward INTEGER
            )
        ''')
        # Использованные промокоды
        await db.execute('''
            CREATE TABLE IF NOT EXISTS used_promos (
                user_id INTEGER,
                code TEXT,
                PRIMARY KEY (user_id, code)
            )
        ''')
        # Настройки
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # Главный админ
        await db.execute('INSERT OR REPLACE INTO admins (user_id, role) VALUES (?, ?)', (INITIAL_ADMIN_ID, 'super'))
        # Мин. вывод по умолчанию
        await db.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('min_withdraw', '100'))
        
        await db.commit()

async def get_admin_role(user_id: int):
    if user_id == INITIAL_ADMIN_ID:
        return 'super'
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT role FROM admins WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def is_banned(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] == 1 if row else False

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id, balance, wins, losses, is_banned FROM users WHERE user_id = ?', (user_id,)) as cursor:
            return await cursor.fetchone()

async def register_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR IGNORE INTO users (user_id, balance, wins, losses, is_banned) VALUES (?, 0, 0, 0, 0)', (user_id,))
        await db.commit()

async def get_min_withdraw() -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT value FROM settings WHERE key = "min_withdraw"') as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 100

# --- Главная Клавиатура ---
def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ Апгрейд звезд"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="💳 Задонатить звезды"), KeyboardButton(text="⚙️ Админ панель")]
        ],
        resize_keyboard=True
    )

# --- Обработчик /start ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if await is_banned(message.from_user.id):
        await message.answer("❌ Вы заблокированы в этом боте.")
        return

    await register_user(message.from_user.id)
    
    welcome_text = (
        f"👋 Добро пожаловать в ⭐ Stars Casino!\n\n"
        f"Здесь вы можете испытывать удачу и делать апгрейд звезд!\n"
        f"Используйте меню ниже для навигации."
    )
    await message.answer(welcome_text, reply_markup=main_kb())

# --- Вкладка Профиль ---
@router.message(F.text == "👤 Профиль")
async def profile_menu(message: Message):
    if await is_banned(message.from_user.id):
        return

    user = await get_user(message.from_user.id)
    if not user:
        await register_user(message.from_user.id)
        user = await get_user(message.from_user.id)

    _, balance, wins, losses, _ = user

    text = (
        f"👤 <b>Ваш профиль:</b>\n\n"
        f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n"
        f"⭐ <b>Баланс звезд:</b> {balance} ⭐\n\n"
        f"🏆 <b>Побед:</b> {wins}\n"
        f"💥 <b>Поражений:</b> {losses}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Вывести звезды", callback_data="withdraw_stars")],
        [InlineKeyboardButton(text="🎟 Активировать промокод", callback_data="activate_promo")]
    ])

    await message.answer(text, parse_mode="HTML", reply_markup=kb)

# --- Вкладка Задонатить Звезды ---
@router.message(F.text == "💳 Задонатить звезды")
async def donate_stars(message: Message):
    if await is_banned(message.from_user.id):
        return

    text = (
        "💳 <b>Пополнение баланса звезд:</b>\n\n"
        "Чтобы задонатить звезды, напишите на этот юзернейм:\n"
        "👉 <b>@v1nk_molik</b>\n\n"
        "Укажите ваш ID и количество звезд, которое хотите приобрести, "
        "и после оплаты они будут моментально начислены на ваш баланс!"
    )
    await message.answer(text, parse_mode="HTML")

# --- Вкладка Апгрейд Звезд (Казино х2) ---
@router.message(F.text == "⭐ Апгрейд звезд")
async def upgrade_stars_start(message: Message, state: FSMContext):
    if await is_banned(message.from_user.id):
        return

    user = await get_user(message.from_user.id)
    balance = user[1]

    if balance <= 0:
        await message.answer("❌ У вас 0 звезд на балансе! Задонатьте звезды через вкладку «💳 Задонатить звезды», чтобы начать играть.")
        return

    await state.set_state(GameStates.waiting_for_bet)
    await message.answer(
        f"🎰 <b>Апгрейд звезд (Множитель x2)</b>\n\n"
        f"Ваш текущий баланс: <b>{balance} ⭐</b>\n\n"
        f"Введите количество звезд, которое хотите поставить на апгрейд:"
    , parse_mode="HTML")

@router.message(GameStates.waiting_for_bet)
async def process_bet(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите корректное число звезд.")
        return

    bet = int(message.text)
    user = await get_user(message.from_user.id)
    balance = user[1]

    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0.")
        return

    if bet > balance:
        await message.answer(f"❌ У вас недостаточно звезд! Ваш баланс: {balance} ⭐.")
        return

    # Логика подкрутки: шанс выигрыша 35%, множитель x2
    win = random.random() < 0.35

    async with aiosqlite.connect(DB_NAME) as db:
        if win:
            multiplier = 2.0
            win_amount = int(bet * multiplier)
            profit = win_amount - bet
            await db.execute(
                'UPDATE users SET balance = balance + ?, wins = wins + 1 WHERE user_id = ?',
                (profit, message.from_user.id)
            )
            await db.commit()
            new_balance = balance + profit
            await message.answer(
                f"🎉 <b>ПОБЕДА!</b>\n\n"
                f"Вы выиграли {win_amount} ⭐ (x2)!\n"
                f"Твой новый баланс: <b>{new_balance} ⭐</b>",
                parse_mode="HTML"
            )
        else:
            await db.execute(
                'UPDATE users SET balance = balance - ?, losses = losses + 1 WHERE user_id = ?',
                (bet, message.from_user.id)
            )
            await db.commit()
            new_balance = balance - bet
            await message.answer(
                f"💥 <b>НЕУДАЧА!</b>\n\n"
                f"Ваша ставка в {bet} ⭐ сгорела.\n"
                f"Твой новый баланс: <b>{new_balance} ⭐</b>",
                parse_mode="HTML"
            )

    await state.clear()

# --- Вывод звезд (Пользователь) ---
@router.callback_query(F.data == "withdraw_stars")
async def withdraw_start(call: CallbackQuery, state: FSMContext):
    user = await get_user(call.from_user.id)
    balance = user[1]
    min_w = await get_min_withdraw()

    if balance < min_w:
        await call.answer(f"❌ Минимальный вывод: {min_w} ⭐. У вас: {balance} ⭐", show_alert=True)
        return

    await state.set_state(WithdrawStates.waiting_for_amount)
    await call.message.answer(f"📤 Введите количество звезд для вывода (Минимум: {min_w} ⭐, Баланс: {balance} ⭐):")
    await call.answer()

@router.message(WithdrawStates.waiting_for_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Пожалуйста, введите число.")
        return

    amount = int(message.text)
    user = await get_user(message.from_user.id)
    balance = user[1]
    min_w = await get_min_withdraw()

    if amount < min_w:
        await message.answer(f"❌ Минимальная сумма вывода составляет {min_w} ⭐.")
        return

    if amount > balance:
        await message.answer(f"❌ У вас недостаточно звезд на балансе.")
        return

    await state.update_data(withdraw_amount=amount)
    await state.set_state(WithdrawStates.waiting_for_address)
    await message.answer("📝 Напишите ваш Telegram юзернейм или реквизиты для получения вывода:")

@router.message(WithdrawStates.waiting_for_address)
async def process_withdraw_address(message: Message, state: FSMContext):
    address = message.text
    data = await state.get_data()
    amount = data['withdraw_amount']
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        # Списываем звезды с баланса сразу, чтобы не проиграл их пока ждет
        await db.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
        await db.execute('INSERT INTO withdrawals (user_id, amount, address, status) VALUES (?, ?, ?, "pending")', (user_id, amount, address))
        await db.commit()

    await message.answer(f"✅ Заявка на вывод {amount} ⭐ успешно создана и передана администраторам!")
    await state.clear()

# --- Промокоды ---
@router.callback_query(F.data == "activate_promo")
async def promo_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.waiting_for_code)
    await call.message.answer("🎟 Введите название промокода:")
    await call.answer()

@router.message(PromoStates.waiting_for_code)
async def process_promo(message: Message, state: FSMContext):
    code = message.text.strip()
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT 1 FROM used_promos WHERE user_id = ? AND code = ?', (user_id, code)) as cursor:
            if await cursor.fetchone():
                await message.answer("❌ Вы уже активировали этот промокод!")
                await state.clear()
                return

        async with db.execute('SELECT activations_left, stars_reward FROM promo_codes WHERE code = ?', (code,)) as cursor:
            promo = await cursor.fetchone()

        if not promo:
            await message.answer("❌ Такого промокода не существует!")
            await state.clear()
            return

        activations, reward = promo
        if activations <= 0:
            await message.answer("❌ У этого промокода закончились активации!")
            await state.clear()
            return

        await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
        await db.execute('UPDATE promo_codes SET activations_left = activations_left - 1 WHERE code = ?', (code,))
        await db.execute('INSERT INTO used_promos (user_id, code) VALUES (?, ?)', (user_id, code))
        await db.commit()

    await message.answer(f"🎉 Промокод успешно активирован! Вам начислено <b>+{reward} ⭐</b>!", parse_mode="HTML")
    await state.clear()

# --- АДМИН ПАНЕЛЬ С РОЛЯМИ ---
@router.message(F.text == "⚙️ Админ панель")
async def admin_panel(message: Message):
    role = await get_admin_role(message.from_user.id)
    if not role:
        return

    role_title = "🔴 Старший админ" if role == "super" else "🔵 Младший админ"
    text = f"⚙️ <b>Панель администратора ({role_title}):</b>"

    buttons = []
    if role == "super":
        buttons.append([
            InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add"),
            InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_del")
        ])

    buttons.extend([
        [InlineKeyboardButton(text="📤 Заявки на вывод", callback_data="admin_withdrawals_list")],
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="admin_ban"), InlineKeyboardButton(text="🟢 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton(text="➕ Выдать звезды", callback_data="admin_give"), InlineKeyboardButton(text="➖ Забрать звезды", callback_data="admin_take")],
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin_promo"), InlineKeyboardButton(text="⚙️ Мин. вывод", callback_data="admin_min_withdraw")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")]
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

# Просмотр заявок на вывод
@router.callback_query(F.data == "admin_withdrawals_list")
async def admin_withdrawals_list(call: CallbackQuery):
    if not await get_admin_role(call.from_user.id): return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT id, user_id, amount, address FROM withdrawals WHERE status = "pending" LIMIT 5') as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await call.answer("📭 Активных заявок на вывод нет.", show_alert=True)
        return

    await call.message.answer("📤 <b>Список ожидающих заявок на вывод:</b>", parse_mode="HTML")
    for req_id, uid, amount, address in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"wd_accept_{req_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"wd_reject_{req_id}")
            ]
        ])
        text = (
            f"🆔 Заявка №<code>{req_id}</code>\n"
            f"👤 ID игрока: <code>{uid}</code>\n"
            f"⭐ Сумма: <b>{amount} ⭐</b>\n"
            f"📝 Реквизиты: {address}"
        )
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()

# Обработка заявки (Принять / Отклонить)
@router.callback_query(F.data.startswith("wd_"))
async def process_withdrawal_action(call: CallbackQuery):
    if not await get_admin_role(call.from_user.id): return
    
    action, req_id_str = call.data.split("_")[1], call.data.split("_")[2]
    req_id = int(req_id_str)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id, amount, status FROM withdrawals WHERE id = ?', (req_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            await call.message.edit_text("❌ Заявка не найдена или уже обработана.")
            return

        uid, amount, status = row
        if status != "pending":
            await call.message.edit_text("❌ Эта заявка уже была обработана ранее.")
            return

        if action == "accept":
            await db.execute('UPDATE withdrawals SET status = "accepted" WHERE id = ?', (req_id,))
            await db.commit()
            await call.message.edit_text(f"✅ Заявка №{req_id} <b>принята</b> администратором.", parse_mode="HTML")
            try:
                await bot.send_message(uid, f"✅ Ваша заявка на вывод <b>{amount} ⭐</b> успешно выплачена администратором!", parse_mode="HTML")
            except Exception:
                pass
        elif action == "reject":
            # Возвращаем звезды пользователю
            await db.execute('UPDATE withdrawals SET status = "rejected" WHERE id = ?', (req_id,))
            await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, uid))
            await db.commit()
            await call.message.edit_text(f"❌ Заявка №{req_id} <b>отклонена</b>, звезды возвращены игроку.", parse_mode="HTML")
            try:
                await bot.send_message(uid, f"❌ Ваша заявка на вывод <b>{amount} ⭐</b> была отклонена администратором. Звезды возвращены на ваш баланс.", parse_mode="HTML")
            except Exception:
                pass

    await call.answer()

# Добавить админа
@router.callback_query(F.data == "admin_add")
async def admin_add_cb(call: CallbackQuery, state: FSMContext):
    if await get_admin_role(call.from_user.id) != "super":
        await call.answer("❌ Функция доступна только Старшему Администратору!", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_add_admin_id)
    await call.message.answer("Введите ID пользователя для назначения админом:")
    await call.answer()

@router.message(AdminStates.waiting_for_add_admin_id)
async def process_admin_add_id(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ ID должен состоять из цифр.")
    uid = int(message.text)
    await state.update_data(new_admin_id=uid)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Старший админ (Всё)", callback_data="set_role_super")],
        [InlineKeyboardButton(text="🔵 Младший админ (Без добавления/удаления)", callback_data="set_role_junior")]
    ])
    await message.answer(f"Выберите уровень прав для пользователя <code>{uid}</code>:", parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data.in_({"set_role_super", "set_role_junior"}))
async def process_admin_role_select(call: CallbackQuery, state: FSMContext):
    role_to_set = "super" if call.data == "set_role_super" else "junior"
    data = await state.get_data()
    uid = data.get('new_admin_id')

    if not uid:
        await call.message.answer("❌ Ошибка получения ID.")
        await state.clear()
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR REPLACE INTO admins (user_id, role) VALUES (?, ?)', (uid, role_to_set))
        await db.commit()

    role_text = "Старший администратор" if role_to_set == "super" else "Младший администратор"
    await call.message.answer(f"✅ Пользователь <code>{uid}</code> назначен как <b>{role_text}</b>.", parse_mode="HTML")
    await state.clear()
    await call.answer()

# Удалить админа
@router.callback_query(F.data == "admin_del")
async def admin_del_cb(call: CallbackQuery, state: FSMContext):
    if await get_admin_role(call.from_user.id) != "super":
        await call.answer("❌ Функция доступна только Старшему Администратору!", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_del_admin)
    await call.message.answer("Введите ID админа для удаления:")
    await call.answer()

@router.message(AdminStates.waiting_for_del_admin)
async def process_admin_del(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ ID должен состоять из цифр.")
    uid = int(message.text)
    if uid == INITIAL_ADMIN_ID:
        await message.answer("❌ Нельзя удалить главного владельца!")
        await state.clear()
        return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM admins WHERE user_id = ?', (uid,))
        await db.commit()
    await message.answer(f"✅ Пользователь {uid} удален из админов.")
    await state.clear()

# Забанить
@router.callback_query(F.data == "admin_ban")
async def admin_ban_cb(call: CallbackQuery, state: FSMContext):
    if not await get_admin_role(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_ban_user)
    await call.message.answer("Введите ID пользователя для бана:")
    await call.answer()

@router.message(AdminStates.waiting_for_ban_user)
async def process_admin_ban(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ ID должен состоять из цифр.")
    uid = int(message.text)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (uid,))
        await db.commit()
    await message.answer(f"🚫 Пользователь {uid} забанен.")
    await state.clear()

# Разбанить
@router.callback_query(F.data == "admin_unban")
async def admin_unban_cb(call: CallbackQuery, state: FSMContext):
    if not await get_admin_role(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_unban_user)
    await call.message.answer("Введите ID пользователя для разбана:")
    await call.answer()

@router.message(AdminStates.waiting_for_unban_user)
async def process_admin_unban(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ ID должен состоять из цифр.")
    uid = int(message.text)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (uid,))
        await db.commit()
    await message.answer(f"🟢 Пользователь {uid} разбанен.")
    await state.clear()

# Выдать звезды
@router.callback_query(F.data == "admin_give")
async def admin_give_cb(call: CallbackQuery, state: FSMContext):
    if not await get_admin_role(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_give_stars_user)
    await call.message.answer("Введите ID пользователя для выдачи звезд:")
    await call.answer()

@router.message(AdminStates.waiting_for_give_stars_user)
async def process_give_user(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ ID должен состоять из цифр.")
    await state.update_data(target_user=int(message.text))
    await state.set_state(AdminStates.waiting_for_give_stars_amount)
    await message.answer("Введите количество звезд для выдачи:")

@router.message(AdminStates.waiting_for_give_stars_amount)
async def process_give_amount(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Введите число.")
    amount = int(message.text)
    data = await state.get_data()
    uid = data['target_user']

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, uid))
        await db.commit()

    await message.answer(f"✅ Пользователю {uid} успешно выдано {amount} ⭐.")
    await state.clear()

# Забрать звезды
@router.callback_query(F.data == "admin_take")
async def admin_take_cb(call: CallbackQuery, state: FSMContext):
    if not await get_admin_role(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_take_stars_user)
    await call.message.answer("Введите ID пользователя для списания звезд:")
    await call.answer()

@router.message(AdminStates.waiting_for_take_stars_user)
async def process_take_user(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ ID должен состоять из цифр.")
    await state.update_data(target_user=int(message.text))
    await state.set_state(AdminStates.waiting_for_take_stars_amount)
    await message.answer("Введите количество звезд для списания:")

@router.message(AdminStates.waiting_for_take_stars_amount)
async def process_take_amount(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Введите число.")
    amount = int(message.text)
    data = await state.get_data()
    uid = data['target_user']

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET balance = MAX(0, balance - ?) WHERE user_id = ?', (amount, uid))
        await db.commit()

    await message.answer(f"✅ У пользователя {uid} списано {amount} ⭐.")
    await state.clear()

# Создание промокода
@router.callback_query(F.data == "admin_promo")
async def admin_promo_cb(call: CallbackQuery, state: FSMContext):
    if not await get_admin_role(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_promo_name)
    await call.message.answer("Введите название нового промокода:")
    await call.answer()

@router.message(AdminStates.waiting_for_promo_name)
async def process_promo_name(message: Message, state: FSMContext):
    await state.update_data(promo_name=message.text.strip())
    await state.set_state(AdminStates.waiting_for_promo_activations)
    await message.answer("Введите количество активаций:")

@router.message(AdminStates.waiting_for_promo_activations)
async def process_promo_acts(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Введите число.")
    await state.update_data(promo_acts=int(message.text))
    await state.set_state(AdminStates.waiting_for_promo_stars)
    await message.answer("Введите количество звезд за активацию:")

@router.message(AdminStates.waiting_for_promo_stars)
async def process_promo_stars(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Введите число.")
    stars = int(message.text)
    data = await state.get_data()
    name = data['promo_name']
    acts = data['promo_acts']

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR REPLACE INTO promo_codes (code, activations_left, stars_reward) VALUES (?, ?, ?)', (name, acts, stars))
        await db.commit()

    await message.answer(f"✅ Промокод <code>{name}</code> успешно создан!\nАктиваций: {acts}, Награда: {stars} ⭐", parse_mode="HTML")
    await state.clear()

# Установить мин. вывод
@router.callback_query(F.data == "admin_min_withdraw")
async def admin_min_w_cb(call: CallbackQuery, state: FSMContext):
    if not await get_admin_role(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_min_withdraw)
    cur_min = await get_min_withdraw()
    await call.message.answer(f"Текущий минимальный вывод: {cur_min} ⭐\nВведите новое значение минимального вывода:")
    await call.answer()

@router.message(AdminStates.waiting_for_min_withdraw)
async def process_min_w(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Введите число.")
    new_min = int(message.text)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("min_withdraw", ?)', (str(new_min),))
        await db.commit()

    await message.answer(f"✅ Минимальный вывод установлен на {new_min} ⭐.")
    await state.clear()

# Рассылка
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_cb(call: CallbackQuery, state: FSMContext):
    if not await get_admin_role(call.from_user.id): return
    await state.set_state(AdminStates.waiting_for_broadcast)
    await call.message.answer("Введите сообщение для рассылки всем пользователям:")
    await call.answer()

@router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    broadcast_text = message.text
    count = 0

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id FROM users WHERE is_banned = 0') as cursor:
            users = await cursor.fetchall()

    for user in users:
        try:
            await bot.send_message(user[0], broadcast_text)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await message.answer(f"📢 Рассылка завершена! Сообщение получили {count} пользователей.")
    await state.clear()

# --- Веб-сервер для прохождения Health Check на Render ---
from aiohttp import web

async def handle_health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# --- Запуск Ботa ---
async def main():
    await init_db()
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
