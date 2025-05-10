import logging
import asyncio
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import threading

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import Command

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация Flask
app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

# Конфигурация бота
API_TOKEN = '7731278147:AAGNBi8Td-kSWr0Hhxdh0r46fXKzVsI0S2w'
CHANNEL_ID = '-1002587647993'
CHANNEL_LINK = 'https://t.me/+KZeOjH5orpRiNjgy'
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)

# Админские данные
ADMIN_PASSWORD = 'LegerisKEY-738197481275618273858173'
ADMIN_ID = 5033892308

# Инициализация SQLite
conn = sqlite3.connect('legeris.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    chat_id INTEGER,
    join_date TEXT,
    is_admin INTEGER DEFAULT 0,
    is_subscribed INTEGER DEFAULT 0,
    last_subscription_change TEXT,
    is_banned INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS channels (
    channel_id INTEGER PRIMARY KEY,
    title TEXT,
    welcome_message TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    action TEXT,
    details TEXT,
    timestamp TEXT
)
''')
conn.commit()

# Логирование действий админа
def log_admin_action(admin_id, action, details):
    try:
        cursor.execute('''
        INSERT INTO activity_logs (admin_id, action, details, timestamp)
        VALUES (?, ?, ?, ?)
        ''', (admin_id, action, details, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка логирования действия админа: {str(e)}")

# Проверка подписки
async def check_subscription(user_id: int) -> bool:
    try:
        logger.info(f"Проверка подписки для пользователя {user_id} в канале {CHANNEL_ID}")
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        is_subscribed = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        logger.info(f"Статус подписки пользователя {user_id}: {member.status}, is_subscribed: {is_subscribed}")
        
        cursor.execute('''
            UPDATE users 
            SET is_subscribed = ?, last_subscription_change = ?
            WHERE user_id = ?
        ''', (1 if is_subscribed else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
        conn.commit()
        
        return is_subscribed
    except Exception as e:
        logger.error(f"Ошибка проверки подписки для {user_id}: {str(e)}")
        return False

# Безопасная отправка сообщения
async def send_message_safe(chat_id: int, text: str) -> bool:
    try:
        await bot.send_message(chat_id, text)
        logger.info(f"Сообщение отправлено пользователю {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения пользователю {chat_id}: {str(e)}")
        return False

# Команда /start
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    chat_id = message.chat.id
    join_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()

        if not user:
            cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_name, chat_id, join_date)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, chat_id, join_date))
            conn.commit()
            logger.info(f"Новый пользователь зарегистрирован: {user_id} - {username}")
    except Exception as e:
        logger.error(f"Ошибка базы данных при регистрации пользователя {user_id}: {str(e)}")

    await message.answer("Привет! Я бот для канала Legeris. Используй /help для списка команд.")

# Callback для проверки подписки
@dp.callback_query(lambda c: c.data == "check_subscription")
async def check_subscription_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if await check_subscription(user_id):
        try:
            cursor.execute('SELECT welcome_message FROM channels LIMIT 1')
            welcome_msg = cursor.fetchone()
            msg = welcome_msg[0] if welcome_msg and welcome_msg[0] else "Спасибо за подписку! Вы добавлены в канал."
            await callback_query.message.edit_text(msg)
        except Exception as e:
            logger.error(f"Ошибка базы данных при получении приветственного сообщения: {str(e)}")
            await callback_query.message.edit_text("Произошла ошибка. Попробуйте позже.")
    else:
        await callback_query.answer("Вы не подписаны на канал. Пожалуйста, подпишитесь и попробуйте снова.", show_alert=True)

# Проверка авторизации админа
def check_admin_auth(admin_id):
    if 'admin_id' not in session or session['admin_id'] != admin_id:
        return False
    
    try:
        cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (admin_id,))
        result = cursor.fetchone()
        return result and result[0] == 1
    except Exception as e:
        logger.error(f"Ошибка базы данных при проверке админа {admin_id}: {str(e)}")
        return False

# Маршруты Flask
@app.route('/', methods=['GET', 'POST'])
def admin_panel():
    if request.method == 'POST':
        admin_id = request.form.get('admin_id')
        password = request.form.get('password')
        try:
            admin_id = int(admin_id)
            if password == ADMIN_PASSWORD:
                cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (admin_id,))
                result = cursor.fetchone()
                if result and result[0] == 1:
                    session['admin_id'] = admin_id
                    log_admin_action(admin_id, "Вход", "Админ вошел в систему")
                    return redirect(url_for('admin_dashboard', admin_id=admin_id))
                else:
                    if admin_id == ADMIN_ID:
                        cursor.execute('INSERT OR REPLACE INTO users (user_id, is_admin) VALUES (?, ?)', (admin_id, 1))
                        conn.commit()
                        logger.info(f"Админ {admin_id} добавлен вручную при авторизации")
                        session['admin_id'] = admin_id
                        log_admin_action(admin_id, "Вход", "Админ вошел в систему (добавлен вручную)")
                        return redirect(url_for('admin_dashboard', admin_id=admin_id))
                    flash('У вас нет прав администратора.')
            else:
                flash('Неверный пароль.')
        except ValueError:
            flash('Введите корректный ID администратора.')
        except Exception as e:
            logger.error(f"Ошибка базы данных при проверке админа {admin_id}: {str(e)}")
            flash('Произошла ошибка. Попробуйте позже.')
    return render_template('admin_dashboard.html', login_page=True)

# ... (остальные маршруты Flask остаются без изменений)

# Инициализация базы данных
def init_db():
    try:
        cursor.execute('SELECT COUNT(*) FROM channels')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO channels (channel_id, title, welcome_message) VALUES (?, ?, ?)', 
                          (-1002587647993, "Legeris Channel", "Добро пожаловать в наш канал! Спасибо за подписку."))
            conn.commit()
        
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (ADMIN_ID,))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO users (user_id, is_admin) VALUES (?, ?)', (ADMIN_ID, 1))
            conn.commit()
            logger.info(f"Админ {ADMIN_ID} успешно добавлен в базу данных")
        else:
            logger.info(f"Админ {ADMIN_ID} уже существует в базе данных")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {str(e)}")

# Асинхронный запуск бота
async def start_bot():
    try:
        logger.info("Запуск бота...")
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")

# Запуск бота в отдельном потоке
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_bot())
    loop.close()

# Инициализация приложения
init_db()  # Вызываем синхронно перед запуском

if __name__ == '__main__':
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
