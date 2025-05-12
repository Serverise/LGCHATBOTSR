import os
import logging
import aiosqlite
import asyncio
import json
from datetime import datetime, timedelta
from aiohttp import web, ClientSession
from aiohttp_session import setup, get_session, SimpleCookieStorage
from jinja2 import Environment, FileSystemLoader
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.exceptions import TelegramAPIError

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Настройка Jinja2
template_env = Environment(loader=FileSystemLoader('templates'))

# Инициализация базы данных SQLite
async def init_db():
    try:
        async with aiosqlite.connect('database.db') as conn:
            c = await conn.cursor()
            await c.execute('''CREATE TABLE IF NOT EXISTS admins (
                admin_id TEXT PRIMARY KEY,
                password TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            await c.execute('''CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                welcome_message TEXT
            )''')
            await c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_subscribed BOOLEAN DEFAULT 0,
                is_admin BOOLEAN DEFAULT 0,
                is_banned BOOLEAN DEFAULT 0
            )''')
            await c.execute('''CREATE TABLE IF NOT EXISTS activity_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id TEXT,
                action TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            await c.execute("INSERT OR IGNORE INTO admins (admin_id, password) VALUES (?, ?)",
                            ("5033892308", "LegerisKEY-23489610917034123480152398"))
            await c.execute("INSERT OR IGNORE INTO settings (id, welcome_message) VALUES (?, ?)",
                            (1, "Добро пожаловать в бот!"))
            await conn.commit()
            logger.info("Админ 5033892308 успешно добавлен в базу данных")
    except aiosqlite.Error as e:
        logger.error(f"Ошибка базы данных: {e}")

# Инициализация бота и диспетчера
BOT_TOKEN = os.getenv('BOT_TOKEN', '7731278147:AAGNBi8Td-kSWr0Hhxdh0r46fXKzVsI0S2w')
CHANNEL_ID = '-1002480737204'
CHANNEL_INVITE_LINK = 'https://t.me/+2o4OyJcHgeo4ZWIy'
WEBHOOK_PATH = '/webhook'  # Упрощённый путь
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://lgchatbotsr.onrender.com') + WEBHOOK_PATH
SECRET_TOKEN = 'SkibidiLegerisSecret2025'
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Создание приложения aiohttp
app = web.Application()

# Настройка сессий
setup(app, SimpleCookieStorage())

# Функция для получения флэш-сообщений
async def get_flashed_messages(request):
    try:
        session = await get_session(request)
        messages = session.pop('flashed_messages', [])
        return messages
    except Exception as e:
        logger.error(f"Ошибка получения флэш-сообщений: {e}")
        return []

# Проверка авторизации
async def check_auth(request):
    try:
        session = await get_session(request)
        admin_id = session.get('admin_id')
        if not admin_id:
            session.setdefault('flashed_messages', []).append('Требуется авторизация!')
            return None
        return admin_id
    except Exception as e:
        logger.error(f"Ошибка проверки авторизации: {e}")
        return None

# Логирование действий админа
async def log_admin_action(admin_id, action, details):
    try:
        async with aiosqlite.connect('database.db') as conn:
            c = await conn.cursor()
            await c.execute("INSERT INTO activity_logs (admin_id, action, details) VALUES (?, ?, ?)",
                            (admin_id, action, details))
            await conn.commit()
    except aiosqlite.Error as e:
        logger.error(f"Ошибка логирования действия: {e}")

# Рендеринг шаблона с обработкой ошибок
async def render_template(template_name, request, **kwargs):
    try:
        template = template_env.get_template(template_name)
        flashed_messages = await get_flashed_messages(request)
        return web.Response(
            text=template.render(flashed_messages=flashed_messages, **kwargs),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка рендеринга шаблона {template_name}: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Периодическая задача для поддержания активности
async def keep_alive():
    async with ClientSession() as session:
        while True:
            try:
                async with session.get('https://lgchatbotsr.onrender.com') as resp:
                    logger.debug(f"Keep-alive ping: {resp.status}")
            except Exception as e:
                logger.error(f"Ошибка keep-alive: {e}")
            await asyncio.sleep(300)  # Пинг каждые 5 минут

# Маршруты
async def admin_panel(request):
    logger.debug("Обращение к маршруту /")
    return await render_template('admin_login.html', request, login_page=True)

async def login_handler(request):
    try:
        session = await get_session(request)
        data = await request.post()
        admin_id = data.get('admin_id')
        password = data.get('password')
        
        async with aiosqlite.connect('database.db') as conn:
            c = await conn.cursor()
            await c.execute("SELECT password FROM admins WHERE admin_id = ?", (admin_id,))
            result = await c.fetchone()
        
        if result and result[0] == password:
            session['admin_id'] = admin_id
            session.setdefault('flashed_messages', []).append('Успешный вход!')
            await log_admin_action(admin_id, 'login', 'Logged in')
            return web.HTTPFound(f'/admin/{admin_id}')
        else:
            session.setdefault('flashed_messages', []).append('Неверный ID или пароль!')
            return web.HTTPFound('/')
    except Exception as e:
        logger.error(f"Ошибка обработки логина: {e}")
        return web.HTTPFound('/')

async def admin_dashboard(request):
    admin_id = await check_auth(request)
    if not admin_id:
        return web.HTTPFound('/')
    logger.debug(f"Обращение к маршруту /admin/{admin_id}")
    return await render_template('admin_dashboard.html', request, dashboard=True, admin_id=admin_id)

async def logout_handler(request):
    session = await get_session(request)
    admin_id = session.get('admin_id', 'unknown')
    session.clear()
    session.setdefault('flashed_messages', []).append('Вы вышли из системы!')
    await log_admin_action(admin_id, 'logout', 'Logged out')
    return web.HTTPFound('/')

async def edit_welcome(request):
    admin_id = await check_auth(request)
    if not admin_id:
        return web.HTTPFound('/')
    
    if request.method == 'POST':
        try:
            data = await request.post()
            welcome_message = data.get('welcome_message')
            async with aiosqlite.connect('database.db') as conn:
                c = await conn.cursor()
                await c.execute("INSERT OR REPLACE INTO settings (id, welcome_message) VALUES (?, ?)",
                                (1, welcome_message))
                await conn.commit()
            session = await get_session(request)
            session.setdefault('flashed_messages', []).append('Приветственное сообщение обновлено!')
            await log_admin_action(admin_id, 'update_welcome', f'Updated welcome message to: {welcome_message[:50]}...')
            return web.HTTPFound(f'/admin/{admin_id}')
        except Exception as e:
            logger.error(f"Ошибка обработки POST /edit_welcome: {e}")
            return web.HTTPFound(f'/admin/{admin_id}')
    
    async with aiosqlite.connect('database.db') as conn:
        c = await conn.cursor()
        await c.execute("SELECT welcome_message FROM settings WHERE id = 1")
        result = await c.fetchone()
    current_msg = result[0] if result else "Добро пожаловать в бот!"
    
    return await render_template('admin_dashboard.html', request, edit_welcome=True, admin_id=admin_id, current_msg=current_msg)

async def broadcast(request):
    admin_id = await check_auth(request)
    if not admin_id:
        return web.HTTPFound('/')
    session = await get_session(request)
    
    if request.method == 'POST':
        try:
            data = await request.post()
            broadcast_message = data.get('broadcast_message')
            async with aiosqlite.connect('database.db') as conn:
                c = await conn.cursor()
                await c.execute("SELECT user_id FROM users WHERE is_banned = 0")
                users = await c.fetchall()
            
            sent_count = 0
            for user in users:
                try:
                    await bot.send_message(chat_id=user[0], text=broadcast_message)
                    sent_count += 1
                    await asyncio.sleep(0.05)
                except TelegramAPIError as e:
                    logger.warning(f"Не удалось отправить сообщение пользователю {user[0]}: {e}")
            
            session.setdefault('flashed_messages', []).append(f'Рассылка отправлена {sent_count} пользователям!')
            await log_admin_action(admin_id, 'broadcast', f'Sent broadcast to {sent_count} users')
            return web.HTTPFound(f'/admin/{admin_id}')
        except Exception as e:
            logger.error(f"Ошибка обработки POST /broadcast: {e}")
            return web.HTTPFound(f'/admin/{admin_id}')
    
    return await render_template('admin_dashboard.html', request, broadcast=True, admin_id=admin_id)

async def private_message(request):
    admin_id = await check_auth(request)
    if not admin_id:
        return web.HTTPFound('/')
    session = await get_session(request)
    
    if request.method == 'POST':
        try:
            data = await request.post()
            target_user = data.get('target_user')
            private_message = data.get('private_message')
            await bot.send_message(chat_id=target_user, text=private_message)
            session.setdefault('flashed_messages', []).append('Сообщение отправлено!')
            await log_admin_action(admin_id, 'private_message', f'Sent message to user {target_user}')
            return web.HTTPFound(f'/admin/{admin_id}')
        except TelegramAPIError as e:
            session.setdefault('flashed_messages', []).append(f'Ошибка отправки: {str(e)}')
            return web.HTTPFound(f'/admin/{admin_id}')
    
    return await render_template('admin_dashboard.html', request, private_message=True, admin_id=admin_id)

async def user_stats(request):
    admin_id = await check_auth(request)
    if not admin_id:
        return web.HTTPFound('/')
    try:
        async with aiosqlite.connect('database.db') as conn:
            c = await conn.cursor()
            await c.execute("SELECT COUNT(*) FROM users")
            total_users = (await c.fetchone())[0]
            await c.execute("SELECT COUNT(*) FROM users WHERE is_subscribed = 1")
            total_subscribers = (await c.fetchone())[0]
            await c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
            total_banned = (await c.fetchone())[0]
            
            today = datetime.utcnow().strftime('%Y-%m-%d')
            await c.execute("SELECT COUNT(*) FROM users WHERE date(joined_at) = ?", (today,))
            new_today = (await c.fetchone())[0]
            await c.execute("SELECT COUNT(*) FROM users WHERE joined_at >= date('now', '-7 days')")
            new_week = (await c.fetchone())[0]
            await c.execute("SELECT COUNT(*) FROM users WHERE joined_at >= date('now', '-30 days')")
            new_month = (await c.fetchone())[0]
            
            try:
                channel_subscribers = await bot.get_chat_member_count(chat_id=CHANNEL_ID)
                logger.debug(f"Получено количество подписчиков канала {CHANNEL_ID}: {channel_subscribers}")
            except TelegramAPIError as e:
                logger.error(f"Ошибка получения подписчиков канала {CHANNEL_ID}: {e}")
                channel_subscribers = 0
            
            await c.execute("""
                SELECT strftime('%Y-%m', joined_at) AS month, COUNT(*) AS count
                FROM users
                WHERE joined_at >= date('now', '-3 months')
                GROUP BY month
                ORDER BY month
            """)
            chart_data = await c.fetchall()
            labels = [row[0] for row in chart_data]
            data = [row[1] for row in chart_data]
        
        stats = {
            'total_users': total_users,
            'new_today': new_today,
            'new_week': new_week,
            'new_month': new_month,
            'total_subscribers': total_subscribers,
            'total_banned': total_banned,
            'channel_subscribers': channel_subscribers,
            'chart_data': {
                'labels': labels or ['Jan', 'Feb', 'Mar'],
                'datasets': [{'label': 'New Users', 'data': data or [0, 0, 0]}]
            }
        }
        
        return await render_template('admin_dashboard.html', request, stats_page=True, admin_id=admin_id, stats=stats)
    except Exception as e:
        logger.error(f"Ошибка обработки статистики: {e}")
        return web.HTTPFound('/')

async def stats_json(request):
    admin_id = await check_auth(request)
    if not admin_id:
        return web.json_response({'error': 'Unauthorized'}, status=401)
    try:
        async with aiosqlite.connect('database.db') as conn:
            c = await conn.cursor()
            await c.execute("SELECT COUNT(*) FROM users")
            total_users = (await c.fetchone())[0]
            await c.execute("SELECT COUNT(*) FROM users WHERE is_subscribed = 1")
            total_subscribers = (await c.fetchone())[0]
            await c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
            total_banned = (await c.fetchone())[0]
            
            today = datetime.utcnow().strftime('%Y-%m-%d')
            await c.execute("SELECT COUNT(*) FROM users WHERE date(joined_at) = ?", (today,))
            new_today = (await c.fetchone())[0]
            await c.execute("SELECT COUNT(*) FROM users WHERE joined_at >= date('now', '-7 days')")
            new_week = (await c.fetchone())[0]
            await c.execute("SELECT COUNT(*) FROM users WHERE joined_at >= date('now', '-30 days')")
            new_month = (await c.fetchone())[0]
            
            try:
                channel_subscribers = await bot.get_chat_member_count(chat_id=CHANNEL_ID)
                logger.debug(f"Получено количество подписчиков канала {CHANNEL_ID}: {channel_subscribers}")
            except TelegramAPIError as e:
                logger.error(f"Ошибка получения подписчиков канала {CHANNEL_ID}: {e}")
                channel_subscribers = 0
        
        stats = {
            'total_users': total_users,
            'new_today': new_today,
            'new_week': new_week,
            'new_month': new_month,
            'total_subscribers': total_subscribers,
            'total_banned': total_banned,
            'channel_subscribers': channel_subscribers
        }
        
        return web.json_response(stats)
    except Exception as e:
        logger.error(f"Ошибка обработки JSON-статистики: {e}")
        return web.json_response({'error': str(e)}, status=500)

async def user_management(request):
    admin_id = await check_auth(request)
    if not admin_id:
        return web.HTTPFound('/')
    session = await get_session(request)
    
    async with aiosqlite.connect('database.db') as conn:
        c = await conn.cursor()
        
        if request.method == 'POST':
            try:
                data = await request.post()
                action = data.get('action')
                selected_users = data.getlist('selected_users') or [data.get('user_id')]
                
                if action == 'ban':
                    await c.executemany("UPDATE users SET is_banned = 1 WHERE user_id = ?", [(uid,) for uid in selected_users])
                    await log_admin_action(admin_id, 'ban_users', f'Banned users: {", ".join(selected_users)}')
                elif action == 'unban':
                    await c.executemany("UPDATE users SET is_banned = 0 WHERE user_id = ?", [(uid,) for uid in selected_users])
                    await log_admin_action(admin_id, 'unban_users', f'Unbanned users: {", ".join(selected_users)}')
                elif action == 'make_admin':
                    await c.executemany("UPDATE users SET is_admin = 1 WHERE user_id = ?", [(uid,) for uid in selected_users])
                    await log_admin_action(admin_id, 'make_admin', f'Made admin: {", ".join(selected_users)}')
                elif action == 'remove_admin':
                    await c.executemany("UPDATE users SET is_admin = 0 WHERE user_id = ?", [(uid,) for uid in selected_users])
                    await log_admin_action(admin_id, 'remove_admin', f'Removed admin: {", ".join(selected_users)}')
                
                await conn.commit()
                session.setdefault('flashed_messages', []).append(f'Действие {action} выполнено!')
                return web.HTTPFound(f'/admin/{admin_id}')
            except Exception as e:
                logger.error(f"Ошибка обработки POST /user_management: {e}")
                return web.HTTPFound(f'/admin/{admin_id}')
        
        search_query = request.query.get('search', '')
        filter_subscribed = request.query.get('subscribed', '')
        filter_admin = request.query.get('admin', '')
        filter_banned = request.query.get('banned', '')
        
        query = "SELECT user_id, username, first_name, last_name, joined_at, is_subscribed, is_admin, is_banned FROM users WHERE 1=1"
        params = []
        if search_query:
            query += " AND (user_id LIKE ? OR username LIKE ? OR first_name LIKE ? OR last_name LIKE ?)"
            params.extend([f'%{search_query}%'] * 4)
        if filter_subscribed:
            query += " AND is_subscribed = ?"
            params.append(1 if filter_subscribed == 'yes' else 0)
        if filter_admin:
            query += " AND is_admin = ?"
            params.append(1 if filter_admin == 'yes' else 0)
        if filter_banned:
            query += " AND is_banned = ?"
            params.append(1 if filter_banned == 'yes' else 0)
        
        await c.execute(query, params)
        users = await c.fetchall()
    
    return await render_template('admin_dashboard.html', request, user_management=True, admin_id=admin_id, users=users,
                                search_query=search_query, filter_subscribed=filter_subscribed,
                                filter_admin=filter_admin, filter_banned=filter_banned)

async def activity_logs(request):
    admin_id = await check_auth(request)
    if not admin_id:
        return web.HTTPFound('/')
    try:
        async with aiosqlite.connect('database.db') as conn:
            c = await conn.cursor()
            await c.execute("SELECT log_id, admin_id, action, details, timestamp FROM activity_logs ORDER BY timestamp DESC LIMIT 100")
            logs = await c.fetchall()
        
        return await render_template('admin_dashboard.html', request, activity_logs=True, admin_id=admin_id, logs=logs)
    except Exception as e:
        logger.error(f"Ошибка обработки логов активности: {e}")
        return web.HTTPFound('/')

# Проверка подписки на канал
async def check_subscription(user_id):
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        status = chat_member.status in ['member', 'administrator', 'creator']
        logger.debug(f"Проверка подписки user_id {user_id}: {'Подписан' if status else 'Не подписан'}")
        return status
    except TelegramAPIError as e:
        logger.error(f"Ошибка проверки подписки для {user_id}: {e}")
        return False

# Telegram-обработчик команды /start
@dp.message(Command('start'))
async def cmd_start(message: Message):
    try:
        user_id = str(message.from_user.id)
        username = message.from_user.username
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        logger.debug(f"Команда /start от user_id {user_id}")
        
        async with aiosqlite.connect('database.db') as conn:
            c = await conn.cursor()
            await c.execute("""
                INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            """, (user_id, username, first_name, last_name))
            await conn.commit()
        
        is_subscribed = await check_subscription(user_id)
        if is_subscribed:
            async with aiosqlite.connect('database.db') as conn:
                c = await conn.cursor()
                await c.execute("UPDATE users SET is_subscribed = 1 WHERE user_id = ?", (user_id,))
                await conn.commit()
            await message.answer("Вы уже подписаны на канал! Спасибо!")
        else:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Подписаться на канал", url=CHANNEL_INVITE_LINK)],
                    [InlineKeyboardButton(text="Проверить подписку", callback_data="check_subscription")]
                ]
            )
            await message.answer(
                "Пожалуйста, подпишитесь на наш канал, чтобы продолжить!",
                reply_markup=keyboard
            )
    except TelegramAPIError as e:
        logger.error(f"Ошибка обработки команды /start (Telegram): {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка обработки команды /start: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

# Обработчик проверки подписки
@dp.callback_query(lambda c: c.data == 'check_subscription')
async def check_subscription_callback(callback_query):
    try:
        user_id = str(callback_query.from_user.id)
        is_subscribed = await check_subscription(user_id)
        if is_subscribed:
            async with aiosqlite.connect('database.db') as conn:
                c = await conn.cursor()
                await c.execute("UPDATE users SET is_subscribed = 1 WHERE user_id = ?", (user_id,))
                await conn.commit()
            await callback_query.message.edit_text("Спасибо за подписку! Теперь вы можете использовать бот.")
        else:
            await callback_query.message.edit_text(
                "Вы ещё не подписаны на канал. Пожалуйста, подпишитесь!",
                reply_markup=callback_query.message.reply_markup
            )
    except TelegramAPIError as e:
        logger.error(f"Ошибка проверки подписки (Telegram): {e}")
        await callback_query.message.edit_text("Произошла ошибка. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        await callback_query.message.edit_text("Произошла ошибка. Попробуйте позже.")

# Обработчик команды /restart
@dp.message(Command('restart'))
async def cmd_restart(message: Message):
    try:
        if str(message.from_user.id) != '5033892308':
            await message.answer("У вас нет прав для выполнения этой команды.")
            return
        logger.info("Команда /restart выполняется")
        if await set_webhook():
            await message.answer("Вебхук перезапущен успешно!")
        else:
            await message.answer("Ошибка при перезапуске вебхука. Проверьте логи.")
    except TelegramAPIError as e:
        logger.error(f"Ошибка обработки команды /restart (Telegram): {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка обработки команды /restart: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

# Обработчик команды /status
@dp.message(Command('status'))
async def cmd_status(message: Message):
    try:
        if str(message.from_user.id) != '5033892308':
            await message.answer("У вас нет прав для выполнения этой команды.")
            return
        webhook_info = await bot.get_webhook_info()
        status = (
            f"Статус бота:\n"
            f"Вебхук URL: {webhook_info.url}\n"
            f"Pending updates: {webhook_info.pending_update_count}\n"
            f"Max connections: {webhook_info.max_connections}\n"
            f"Last error: {webhook_info.last_error_date or 'None'} - {webhook_info.last_error_message or 'None'}"
        )
        await message.answer(status)
    except TelegramAPIError as e:
        logger.error(f"Ошибка обработки команды /status (Telegram): {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка обработки команды /status: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

# Обработчик всех текстовых сообщений
@dp.message()
async def handle_all_messages(message: Message):
    try:
        user_id = str(message.from_user.id)
        logger.debug(f"Получено сообщение от user_id {user_id}: {message.text}")
        
        # Проверка подписки
        is_subscribed = await check_subscription(user_id)
        if not is_subscribed:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Подписаться на канал", url=CHANNEL_INVITE_LINK)],
                    [InlineKeyboardButton(text="Проверить подписку", callback_data="check_subscription")]
                ]
            )
            await message.answer(
                "Пожалуйста, подпишитесь на наш канал, чтобы продолжить!",
                reply_markup=keyboard
            )
            return
        
        # Ответ на любое сообщение
        await message.answer(f"Я получил ваше сообщение: {message.text}")
    except TelegramAPIError as e:
        logger.error(f"Ошибка обработки сообщения (Telegram): {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

# Настройка вебхука с retry
async def set_webhook():
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            webhook = await bot.get_webhook_info()
            if webhook.url != WEBHOOK_URL or webhook.max_connections < 100:
                await bot.delete_webhook()
                await asyncio.sleep(1)
                await bot.set_webhook(
                    url=WEBHOOK_URL,
                    secret_token=SECRET_TOKEN,
                    max_connections=100,
                    drop_pending_updates=True
                )
                logger.info(f"Вебхук установлен на {WEBHOOK_URL} с secret_token")
            else:
                logger.info("Вебхук уже установлен корректно")
            return True
        except TelegramAPIError as e:
            logger.error(f"Попытка {attempt+1}/{max_attempts} установки вебхука не удалась: {e}")
            await asyncio.sleep(2)
    logger.error("Не удалось установить вебхук после всех попыток")
    return False

# Настройка вебхука при запуске
async def on_startup(app):
    try:
        logger.info("Установка вебхука...")
        await set_webhook()
        await init_db()
        # Запуск keep-alive задачи
        asyncio.create_task(keep_alive())
    except Exception as e:
        logger.error(f"Ошибка при запуске приложения: {e}")

async def on_shutdown(app):
    try:
        logger.info("Остановка бота...")
        await bot.delete_webhook()
        await bot.session.close()
    except Exception as e:
        logger.error(f"Ошибка при остановке приложения: {e}")

# Регистрация маршрутов
routes = [
    web.get('/', admin_panel),
    web.post('/', login_handler),
    web.get('/admin/{admin_id}', admin_dashboard),
    web.get('/logout', logout_handler),
    web.route('*', '/admin/{admin_id}/edit_welcome', edit_welcome),
    web.route('*', '/admin/{admin_id}/broadcast', broadcast),
    web.route('*', '/admin/{admin_id}/private_message', private_message),
    web.route('*', '/admin/{admin_id}/user_stats', user_stats),
    web.get('/admin/{admin_id}/stats_json', stats_json),
    web.route('*', '/admin/{admin_id}/user_management', user_management),
    web.route('*', '/admin/{admin_id}/activity_logs', activity_logs)
]
app.router.add_routes(routes)

# Настройка aiogram с aiohttp
request_handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=SECRET_TOKEN)
request_handler.register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)

# Регистрация хуков жизненного цикла
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# Запуск приложения
if __name__ == '__main__':
    try:
        port = int(os.getenv('PORT', 8080))
        web.run_app(app, port=port)
    except Exception as e:
        logger.error(f"Ошибка запуска приложения: {e}")
