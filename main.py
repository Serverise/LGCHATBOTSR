import logging
import sqlite3
from datetime import datetime
import asyncio
from flask import Flask, request, render_template, redirect, url_for, flash, session
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiohttp_wsgi import WSGIHandler

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
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"https://lgchatbotsr.onrender.com{WEBHOOK_PATH}"

# Использование DefaultBotProperties для настройки parse_mode
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Инициализация базы данных
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

conn.commit()

# Состояния для FSM
class Form(StatesGroup):
    welcome_message = State()
    broadcast_message = State()
    select_user = State()
    private_message = State()

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
@dp.message(CommandStart())
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

    # Проверяем подписку
    if await check_subscription(user_id):
        try:
            cursor.execute('SELECT welcome_message FROM channels LIMIT 1')
            welcome_msg = cursor.fetchone()
            msg = welcome_msg[0] if welcome_msg and welcome_msg[0] else "Спасибо за подписку! Вы добавлены в канал."
            
            # Инициализация клавиатуры с кнопками
            keyboard_buttons = []
            cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            is_admin = result[0] if result else 0
            if is_admin:
                keyboard_buttons.append([KeyboardButton(text="Панель управления")])
            
            keyboard = ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)
            await message.answer(msg, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Ошибка при отправке приветственного сообщения: {str(e)}")
            await message.answer("Произошла ошибка. Попробуйте позже.")
    else:
        # Инициализация клавиатуры с кнопками
        keyboard_buttons = [[KeyboardButton(text="Подписаться на канал")]]
        cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        is_admin = result[0] if result else 0
        if is_admin:
            keyboard_buttons.append([KeyboardButton(text="Панель управления")])
        
        keyboard = ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)
        await message.answer(
            f"Пожалуйста, подпишитесь на канал по ссылке: {CHANNEL_LINK}",
            reply_markup=keyboard
        )

# Обработка кнопки "Подписаться на канал"
@dp.message(lambda message: message.text == "Подписаться на канал")
async def subscribe_channel(message: types.Message):
    user_id = message.from_user.id
    if await check_subscription(user_id):
        cursor.execute('SELECT welcome_message FROM channels LIMIT 1')
        welcome_msg = cursor.fetchone()
        msg = welcome_msg[0] if welcome_msg and welcome_msg[0] else "Спасибо за подписку! Вы добавлены в канал."
        
        # Инициализация клавиатуры с кнопками
        keyboard_buttons = []
        cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        is_admin = result[0] if result else 0
        if is_admin:
            keyboard_buttons.append([KeyboardButton(text="Панель управления")])
        
        keyboard = ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)
        await message.answer(msg, reply_markup=keyboard)
    else:
        keyboard_buttons = [[KeyboardButton(text="Подписаться на канал")]]
        await message.answer(
            f"Вы не подписаны на канал. Пожалуйста, подпишитесь по ссылке: {CHANNEL_LINK}",
            reply_markup=ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)
        )

# Панель управления для админов
@dp.message(lambda message: message.text == "Панель управления")
async def admin_panel(message: types.Message):
    user_id = message.from_user.id
    cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    is_admin = result[0] if result else 0
    if not is_admin:
        await message.answer("У вас нет доступа к этой функции.")
        return
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Изменить приветственное сообщение", callback_data="edit_welcome"))
    keyboard.add(InlineKeyboardButton("Сделать рассылку", callback_data="broadcast"))
    keyboard.add(InlineKeyboardButton("Отправить личное сообщение", callback_data="private_message"))
    keyboard.add(InlineKeyboardButton("Статистика пользователей", callback_data="user_stats"))
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
        await bot.send_message(user_id, "Введите сообщение для рассылки всем пользователям:")
    
    elif callback_query.data == "private_message":
        await Form.select_user.set()
        await bot.send_message(user_id, "Введите ID пользователя, которому хотите отправить сообщение:")
    
    elif callback_query.data == "user_stats":
        try:
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) = date("now")')
            new_today = cursor.fetchone()[0]
            stats = f"📊 Статистика пользователей:\n\nВсего пользователей: {total_users}\nНовых сегодня: {new_today}"
            await bot.send_message(user_id, stats)
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {str(e)}")
            await bot.send_message(user_id, "Ошибка при получении статистики. Попробуйте позже.")

# Обработка ввода приветственного сообщения
@dp.message(StateFilter(Form.welcome_message))
async def process_welcome_message(message: types.Message, state: FSMContext):
    welcome_msg = message.text
    try:
        cursor.execute('UPDATE channels SET welcome_message = ? WHERE rowid = 1', (welcome_msg,))
        conn.commit()
        await state.finish()
        await message.answer("Приветственное сообщение успешно обновлено!")
    except Exception as e:
        logger.error(f"Ошибка при обновлении приветственного сообщения: {str(e)}")
        await message.answer("Ошибка при обновлении сообщения. Попробуйте позже.")

# Обработка ввода сообщения для рассылки
@dp.message(StateFilter(Form.broadcast_message))
async def process_broadcast(message: types.Message, state: FSMContext):
    broadcast_msg = message.text
    try:
        cursor.execute('SELECT user_id FROM users WHERE is_banned = 0 AND is_subscribed = 1')
        users = cursor.fetchall()
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
    except Exception as e:
        logger.error(f"Ошибка при рассылке: {str(e)}")
        await message.answer("Ошибка при выполнении рассылки. Попробуйте позже.")

# Обработка выбора пользователя для личного сообщения
@dp.message(StateFilter(Form.select_user))
async def process_select_user(message: types.Message, state: FSMContext):
    try:
        target_user = int(message.text)
        await state.update_data(target_user=target_user)
        await Form.private_message.set()
        await message.answer("Введите сообщение для этого пользователя:")
    except ValueError:
        await message.answer("Пожалуйста, введите корректный ID пользователя (только цифры).")
    except Exception as e:
        logger.error(f"Ошибка при выборе пользователя: {str(e)}")
        await message.answer("Произошла ошибка. Попробуйте снова.")

# Обработка личного сообщения
@dp.message(StateFilter(Form.private_message))
async def process_private_message(message: types.Message, state: FSMContext):
    private_msg = message.text
    data = await state.get_data()
    target_user = data.get('target_user')
    if await send_message_safe(target_user, private_msg):
        await message.answer(f"Сообщение успешно отправлено пользователю {target_user}")
    else:
        await message.answer(f"Не удалось отправить сообщение пользователю {target_user}")
    await state.finish()

# Инициализация базы данных
def init_db():
    try:
        cursor.execute('SELECT COUNT(*) FROM channels')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO channels (channel_id, title, welcome_message) VALUES (?, ?, ?)', 
                          (-1002587647993, "Legeris Channel", "Добро пожаловать в наш канал! Спасибо за подписку."))
            conn.commit()
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (5033892308,))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO users (user_id, is_admin) VALUES (?, ?)', (5033892308, 1))
            conn.commit()
            logger.info(f"Админ 5033892308 успешно добавлен в базу данных")
        else:
            logger.info(f"Админ 5033892308 уже существует в базе данных")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {str(e)}")

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
    logger.info("Обращение к маршруту /")
    try:
        if request.method == 'POST':
            admin_id = request.form.get('admin_id')
            password = request.form.get('password')
            try:
                admin_id = int(admin_id)
                logger.info(f"Попытка входа с admin_id={admin_id}")
                if password == 'LegerisKEY-738197481275618273858173':
                    cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (admin_id,))
                    result = cursor.fetchone()
                    if result and result[0] == 1:
                        session['admin_id'] = admin_id
                        logger.info(f"Успешный вход для admin_id={admin_id}")
                        return redirect(url_for('admin_dashboard', admin_id=admin_id))
                    flash('У вас нет прав администратора.')
                    logger.warning(f"Нет прав администратора для admin_id={admin_id}")
                else:
                    flash('Неверный пароль.')
                    logger.warning("Неверный пароль")
            except ValueError:
                flash('Введите корректный ID администратора.')
                logger.warning("Некорректный ID администратора")
            except Exception as e:
                logger.error(f"Ошибка базы данных при проверке админа {admin_id}: {str(e)}")
                flash('Произошла ошибка. Попробуйте позже.')
        return render_template('admin_dashboard.html', login_page=True)
    except Exception as e:
        logger.error(f"Ошибка при обработке маршрута /: {str(e)}")
        return "Internal Server Error", 500

@app.route('/admin/<int:admin_id>')
def admin_dashboard(admin_id):
    logger.info(f"Обращение к маршруту /admin/{admin_id}")
    try:
        if not check_admin_auth(admin_id):
            logger.warning(f"Неавторизованный доступ к /admin/{admin_id}")
            return redirect(url_for('admin_panel'))
        return render_template('admin_dashboard.html', admin_id=admin_id, dashboard=True)
    except Exception as e:
        logger.error(f"Ошибка при обработке маршрута /admin/{admin_id}: {str(e)}")
        return "Internal Server Error", 500

# Настройка вебхука
async def on_startup(dispatcher):
    logger.info("Установка вебхука...")
    try:
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url != WEBHOOK_URL:
            await bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"Вебхук установлен на {WEBHOOK_URL}")
        else:
            logger.info("Вебхук уже установлен")
    except Exception as e:
        logger.error(f"Ошибка при установке вебхука: {str(e)}")

async def on_shutdown(dispatcher):
    logger.info("Остановка бота...")
    try:
        await bot.delete_webhook()
        await bot.session.close()
    except Exception as e:
        logger.error(f"Ошибка при остановке бота: {str(e)}")

# Запуск приложения
async def handle_request(request):
    logger.info(f"Обработка запроса: {request.path}")
    wsgi_handler = WSGIHandler(app)
    response = await wsgi_handler(request)
    return response

if __name__ == '__main__':
    logger.info("Запуск приложения...")
    init_db()
    # Настройка aiohttp приложения для вебхуков
    aiohttp_app = web.Application()
    
    # Регистрация маршрута для обработки всех запросов через WSGI
    aiohttp_app.router.add_get('/', handle_request)
    aiohttp_app.router.add_post('/', handle_request)
    aiohttp_app.router.add_get('/{path:.*}', handle_request)
    aiohttp_app.router.add_post('/{path:.*}', handle_request)
    
    # Настройка вебхука для Telegram
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(aiohttp_app, path=WEBHOOK_PATH)
    setup_application(aiohttp_app, dp, bot=bot)

    # Запуск Flask и вебхуков
    from aiohttp.web import run_app
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Запуск сервера на порту {port}...")
    run_app(aiohttp_app, host='0.0.0.0', port=port)
