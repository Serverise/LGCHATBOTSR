import logging
import asyncio
import aiosqlite
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
import threading
import nest_asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, Text
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode, ChatMemberStatus

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Применяем nest_asyncio для поддержки вложенных циклов
nest_asyncio.apply()

# Конфигурация Flask
app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

# Конфигурация бота
API_TOKEN = '7731278147:AAGNBi8Td-kSWr0Hhxdh0r46fXKzVsI0S2w'  # Замените на ваш токен
CHANNEL_ID = '-1002587647993'  # Замените на ваш ID канала
CHANNEL_LINK = 'https://t.me/+KZeOjH5orpRiNjgy'  # Замените на ссылку на канал
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# Путь к базе данных
DB_PATH = 'legeris.db'

# Состояния для FSM
class Form(StatesGroup):
    welcome_message = State()
    broadcast_message = State()
    select_user = State()
    private_message = State()

# Инициализация базы данных
async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute('''
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
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            channel_id INTEGER PRIMARY KEY,
            title TEXT,
            welcome_message TEXT
        )
        ''')
        # Проверка и добавление начальных данных
        await cursor.execute('SELECT COUNT(*) FROM channels')
        if (await cursor.fetchone())[0] == 0:
            await cursor.execute('INSERT INTO channels (channel_id, title, welcome_message) VALUES (?, ?, ?)',
                                (-1002587647993, "Legeris Channel", "Добро пожаловать в наш канал! Спасибо за подписку."))
        await cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (5033892308,))
        if not await cursor.fetchone():
            await cursor.execute('INSERT INTO users (user_id, is_admin) VALUES (?, ?)', (5033892308, 1))
            logger.info("Админ 5033892308 добавлен в базу данных")
        await conn.commit()

# Проверка подписки
async def check_subscription(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        try:
            logger.info(f"Проверка подписки для пользователя {user_id} в канале {CHANNEL_ID}")
            member = await bot.get_chat_member(CHANNEL_ID, user_id)
            is_subscribed = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
            logger.info(f"Статус подписки пользователя {user_id}: {member.status}, is_subscribed: {is_subscribed}")
            
            await cursor.execute('''
                UPDATE users 
                SET is_subscribed = ?, last_subscription_change = ?
                WHERE user_id = ?
            ''', (1 if is_subscribed else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
            await conn.commit()
            
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
@dp.message(Command(commands=['start']))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    chat_id = message.chat.id
    join_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        try:
            await cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            user = await cursor.fetchone()

            if not user:
                await cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, chat_id, join_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, last_name, chat_id, join_date))
                await conn.commit()
                logger.info(f"Новый пользователь зарегистрирован: {user_id} - {username}")
        except Exception as e:
            logger.error(f"Ошибка базы данных при регистрации пользователя {user_id}: {str(e)}")

    # Проверяем подписку
    if await check_subscription(user_id):
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.cursor()
            try:
                await cursor.execute('SELECT welcome_message FROM channels LIMIT 1')
                welcome_msg = await cursor.fetchone()
                msg = welcome_msg[0] if welcome_msg and welcome_msg[0] else "Спасибо за подписку! Вы добавлены в канал."
                await message.answer(msg)
            except Exception as e:
                logger.error(f"Ошибка базы данных при получении приветственного сообщения: {str(e)}")
                await message.answer("Произошла ошибка. Попробуйте позже.")
    else:
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        keyboard.add(KeyboardButton("Подписаться на канал"))
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.cursor()
            await cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
            result = await cursor.fetchone()
            is_admin = result[0] if result else 0
            if is_admin:
                keyboard.add(KeyboardButton("Панель управления"))
        await message.answer(
            f"Пожалуйста, подпишитесь на канал по ссылке: {CHANNEL_LINK}",
            reply_markup=keyboard
        )

# Обработка кнопки "Подписаться на канал"
@dp.message(Text(equals="Подписаться на канал"))
async def subscribe_channel(message: Message):
    user_id = message.from_user.id
    if await check_subscription(user_id):
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.cursor()
            await cursor.execute('SELECT welcome_message FROM channels LIMIT 1')
            welcome_msg = await cursor.fetchone()
            msg = welcome_msg[0] if welcome_msg and welcome_msg[0] else "Спасибо за подписку! Вы добавлены в канал."
            keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
            await cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
            result = await cursor.fetchone()
            is_admin = result[0] if result else 0
            if is_admin:
                keyboard.add(KeyboardButton("Панель управления"))
            await message.answer(msg, reply_markup=keyboard)
    else:
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        keyboard.add(KeyboardButton("Подписаться на канал"))
        await message.answer(
            f"Вы не подписаны на канал. Пожалуйста, подпишитесь по ссылке: {CHANNEL_LINK}",
            reply_markup=keyboard
        )

# Панель управления для админов
@dp.message(Text(equals="Панель управления"))
async def admin_panel(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()
        is_admin = result[0] if result else 0
        if not is_admin:
            await message.answer("У вас нет доступа к этой функции.")
            return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить приветственное сообщение", callback_data="edit_welcome")],
        [InlineKeyboardButton(text="Сделать рассылку", callback_data="broadcast")],
        [InlineKeyboardButton(text="Отправить личное сообщение", callback_data="private_message")],
        [InlineKeyboardButton(text="Статистика пользователей", callback_data="user_stats")]
    ])
    await message.answer("Панель управления администратора:", reply_markup=keyboard)

# Обработка инлайн кнопок
@dp.callback_query(lambda c: c.data in ["edit_welcome", "broadcast", "private_message", "user_stats"])
async def process_admin_buttons(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    user_id = callback_query.from_user.id
    
    if callback_query.data == "edit_welcome":
        await Form.welcome_message.set()
        await bot.send_message(user_id, "Введите новое приветственное сообщение:")
    
    elif callback_query.data == "broadcast":
        await Form.broadcast_message.set()
        await bot.send_message(user_id, "Введите at message to broadcast to all users:")
    
    elif callback_query.data == "private_message":
        await Form.select_user.set()
        await bot.send_message(user_id, "Введите ID пользователя, которому хотите отправить сообщение:")
    
    elif callback_query.data == "user_stats":
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.cursor()
            await cursor.execute('SELECT COUNT(*) FROM users')
            total_users = (await cursor.fetchone())[0]
            await cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) = date("now")')
            new_today = (await cursor.fetchone())[0]
            stats = f"📊 Статистика пользователей:\n\nВсего пользователей: {total_users}\nНовых сегодня: {new_today}"
            await bot.send_message(user_id, stats)

# Обработка ввода приветственного сообщения
@dp.message(Form.welcome_message)
async def process_welcome_message(message: Message, state: FSMContext):
    welcome_msg = message.text
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute('UPDATE channels SET welcome_message = ? WHERE rowid = 1', (welcome_msg,))
        await conn.commit()
    await state.finish()
    await message.answer("Приветственное сообщение успешно обновлено!")

# Обработка ввода сообщения для рассылки
@dp.message(Form.broadcast_message)
async def process_broadcast(message: Message, state: FSMContext):
    broadcast_msg = message.text
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute('SELECT user_id FROM users WHERE is_banned = 0 AND is_subscribed = 1')
        users = await cursor.fetchall()
    success = 0
    failed = 0
    for user in users:
        if await send_message_safe(user[0], broadcast_msg):
            success += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)  # Ограничение скорости
    await state.finish()
    await message.answer(f"Рассылка завершена!\nУспешно: {success}\nНе удалось: {failed}")

# Обработка выбора пользователя для личного сообщения
@dp.message(Form.select_user)
async def process_select_user(message: Message, state: FSMContext):
    try:
        target_user = int(message.text)
        await state.update_data(target_user=target_user)
        await Form.private_message.set()
        await message.answer("Введите сообщение для этого пользователя:")
    except ValueError:
        await message.answer("Пожалуйста, введите корректный ID пользователя (только цифры).")

# Обработка личного сообщения
@dp.message(Form.private_message)
async def process_private_message(message: Message, state: FSMContext):
    private_msg = message.text
    data = await state.get_data()
    target_user = data.get('target_user')
    if await send_message_safe(target_user, private_msg):
        await message.answer(f"Сообщение успешно отправлено пользователю {target_user}")
    else:
        await message.answer(f"Не удалось отправить сообщение пользователю {target_user}")
    await state.finish()

# Проверка авторизации админа
def check_admin_auth(admin_id):
    if 'admin_id' not in session or session['admin_id'] != admin_id:
        return False
    async def check_admin():
        async with aiosqlite.connect(DB_PATH) as connáz
            cursor = await conn.cursor()
            await cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (admin_id,))
            result = await cursor.fetchone()
            return result and result[0] == 1
    return asyncio.run(check_admin())

# Flask: HTML шаблоны
@app.route('/', methods=['GET', 'POST'])
def admin_panel():
    if request.method == 'POST':
        admin_id = request.form.get('admin_id')
        password = request.form.get('password')
        try:
            admin_id = int(admin_id)
            if password == 'LegerisKEY-738197481275618273858173':
                async def check_admin():
                    async with aiosqlite.connect(DB_PATH) as conn:
                        cursor = await conn.cursor()
                        await cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (admin_id,))
                        result = await cursor.fetchone()
                        return result and result[0] == 1
                if asyncio.run(check_admin()):
                    session['admin_id'] = admin_id
                    return redirect(url_for('admin_dashboard', admin_id=admin_id))
                flash('У вас нет прав администратора.')
            else:
                flash('Неверный пароль.')
        except ValueError:
            flash('Введите корректный ID администратора.')
        except Exception as e:
            logger.error(f"Ошибка базы данных при проверке админа {admin_id}: {str(e)}")
            flash('Произошла ошибка. Попробуйте позже.')
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Login</title>
    </head>
    <body>
        <h2>Вход для администратора</h2>
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <ul>
                {% for message in messages %}
                    <li>{{ message }}</li>
                {% endfor %}
                </ul>
            {% endif %}
        {% endwith %}
        <form method="post">
            <label>Admin ID:</label><br>
            <input type="text" name="admin_id"><br>
            <label>Password:</label><br>
            <input type="password" name="password"><br>
            <input type="submit" value="Войти">
        </form>
    </body>
    </html>
    ''')

@app.route('/admin/<int:admin_id>')
def admin_dashboard(admin_id):
    if not check_admin_auth(admin_id):
        return redirect(url_for('admin_panel'))
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Dashboard</title>
    </head>
    <body>
        <h2>Панель администратора</h2>
        <p>Добро пожаловать, Admin ID: {{ admin_id }}</p>
        <a href="{{ url_for('admin_panel') }}">Выйти</a>
    </body>
    </html>
    ''', admin_id=admin_id)

# Асинхронный запуск бота
async def start_bot():
    try:
        logger.info("Запуск бота...")
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")

# Главная функция
async def main():
    await init_db()
    # Запускаем Flask в отдельном потоке
    def run_flask():
        app.run(host='0.0.0.0', port=5000, use_reloader=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем бота
    await start_bot()

if __name__ == '__main__':
    asyncio.run(main())
