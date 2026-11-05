# ROCKET OSINT Bot

Telegram-бот для сбора открытой информации о пользователе.

## Команды
- `/start` — отчёт по себе
- `/report` — обновить отчёт
- `/target` — ответить на сообщение, получить отчёт по человеку

## Локальный запуск
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="ваш_токен"
python bot.py
