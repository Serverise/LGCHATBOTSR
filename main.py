import os
import logging
import sqlite3
import asyncio
from datetime import datetime
from aiohttp import web
from aiohttp_session import setup, get_session, SimpleCookieStorage
from jinja2 import Environment, FileSystemLoader
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройка Jinja2
template_env = Environment(loader=FileSystemLoader('templates'))

# Инициализация базы данных SQLite
def init_db():
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS admins (
            admin_id TEXT PRIMARY KEY,
            password TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            welcome_message TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_subscribed BOOLEAN DEFAULT 0,
            is_admin BOOLEAN DEFAULT 0,
            is_banned BOOLEAN DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS activity_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id TEXT,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute("INSERT OR IGNORE INTO admins (admin_id, password) VALUES (?, ?)",
                  ("5033892308", "LegerisKEY-23489610917034123480152398"))
        c.execute("INSERT OR IGNORE INTO settings (id, welcome_message) VALUES (?, ?)",
                  (1, "Добро пожаловать в бот!"))
        conn.commit()
        logger.info("Админ 5033892308 успешно добавлен в базу данных")
    except sqlite3.Error as e:
        logger.error(f"Ошибка базы данных: {e}")
    finally:
        conn.close()

# Инициализация бота и диспетчера
BOT_TOKEN = os.getenv('BOT_TOKEN', '7731278147:AAGNBi8Td-kSWr0Hhxdh0r46fXKzVsI0S2w')
CHANNEL_ID = '-1002480737204'
CHANNEL_INVITE_LINK = 'https://t.me/+2o4OyJcHgeo4ZWIy'
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://lgchatbotsr.onrender.com') + WEBHOOK_PATH
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Создание приложения aiohttp
app = web.Application()

# Настройка сессий
setup(app, SimpleCookieStorage())

# Функция для получения флэш-сообщений (синхронная для Jinja2)
def get_flashed_messages(request):
    try:
        session = asyncio.run(get_session(request))
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
            raise web.HTTPFound('/')
        return admin_id
    except Exception as e:
        logger.error(f"Ошибка проверки авторизации: {e}")
        raise web.HTTPFound('/')

# Логирование действий админа
def log_admin_action(admin_id, action, details):
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("INSERT INTO activity_logs (admin_id, action, details) VALUES (?, ?, ?)",
                  (admin_id, action, details))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка логирования действия: {e}")
    finally:
        conn.close()

# Обработчик маршрута для страницы логина
async def admin_panel(request):
    try:
        template = template_env.get_template('admin_login.html')
        logger.info("Обращение к маршруту /")
        return web.Response(
            text=template.render(
                login_page=True,
                get_flashed_messages=get_flashed_messages
            ),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка обработки маршрута /: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Обработчик логина
async def login_handler(request):
    try:
        session = await get_session(request)
        data = await request.post()
        admin_id = data.get('admin_id')
        password = data.get('password')
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT password FROM admins WHERE admin_id = ?", (admin_id,))
        result = c.fetchone()
        conn.close()
        
        if result and result[0] == password:
            session['admin_id'] = admin_id
            session.setdefault('flashed_messages', []).append('Успешный вход!')
            log_admin_action(admin_id, 'login', 'Logged in')
            raise web.HTTPFound(f'/admin/{admin_id}')
        else:
            session.setdefault('flashed_messages', []).append('Неверный ID или пароль!')
            raise web.HTTPFound('/')
    except Exception as e:
        logger.error(f"Ошибка обработки логина: {e}")
        raise web.HTTPFound('/')

# Обработчик админ-панели
async def admin_dashboard(request):
    try:
        admin_id = await check_auth(request)
        template = template_env.get_template('admin_dashboard.html')
        logger.info(f"Обращение к маршруту /admin/{admin_id}")
        return web.Response(
            text=template.render(
                dashboard=True,
                admin_id=admin_id,
                get_flashed_messages=get_flashed_messages
            ),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка обработки админ-панели: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Обработчик выхода
async def logout_handler(request):
    try:
        session = await get_session(request)
        admin_id = session.get('admin_id', 'unknown')
        session.clear()
        session.setdefault('flashed_messages', []).append('Вы вышли из системы!')
        log_admin_action(admin_id, 'logout', 'Logged out')
        raise web.HTTPFound('/')
    except Exception as e:
        logger.error(f"Ошибка обработки выхода: {e}")
        raise web.HTTPFound('/')

# Обработчик редактирования приветственного сообщения
async def edit_welcome(request):
    try:
        admin_id = await check_auth(request)
        
        if request.method == 'POST':
            data = await request.post()
            welcome_message = data.get('welcome_message')
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO settings (id, welcome_message) VALUES (?, ?)",
                      (1, welcome_message))
            conn.commit()
            conn.close()
            session = await get_session(request)
            session.setdefault('flashed_messages', []).append('Приветственное сообщение обновлено!')
            log_admin_action(admin_id, 'update_welcome', f'Updated welcome message to: {welcome_message[:50]}...')
            raise web.HTTPFound(f'/admin/{admin_id}')
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT welcome_message FROM settings WHERE id = 1")
        result = c.fetchone()
        current_msg = result[0] if result else "Добро пожаловать в бот!"
        conn.close()
        
        template = template_env.get_template('admin_dashboard.html')
        return web.Response(
            text=template.render(
                edit_welcome=True,
                admin_id=admin_id,
                current_msg=current_msg,
                get_flashed_messages=get_flashed_messages
            ),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка обработки редактирования приветствия: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Обработчик рассылки
async def broadcast(request):
    try:
        admin_id = await check_auth(request)
        session = await get_session(request)
        
        if request.method == 'POST':
            data = await request.post()
            broadcast_message = data.get('broadcast_message')
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("SELECT user_id FROM users WHERE is_banned = 0")
            users = c.fetchall()
            conn.close()
            
            sent_count = 0
            for user in users:
                try:
                    await bot.send_message(chat_id=user[0], text=broadcast_message)
                    sent_count += 1
                except Exception as e:
                    logger.warning(f"Не удалось отправить сообщение пользователю {user[0]}: {e}")
            
            session.setdefault('flashed_messages', []).append(f'Рассылка отправлена {sent_count} пользователям!')
            log_admin_action(admin_id, 'broadcast', f'Sent broadcast to {sent_count} users')
            raise web.HTTPFound(f'/admin/{admin_id}')
        
        template = template_env.get_template('admin_dashboard.html')
        return web.Response(
            text=template.render(
                broadcast=True,
                admin_id=admin_id,
                get_flashed_messages=get_flashed_messages
            ),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка обработки рассылки: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Обработчик личных сообщений
async def private_message(request):
    try:
        admin_id = await check_auth(request)
        session = await get_session(request)
        
        if request.method == 'POST':
            data = await request.post()
            target_user = data.get('target_user')
            private_message = data.get('private_message')
            try:
                await bot.send_message(chat_id=target_user, text=private_message)
                session.setdefault('flashed_messages', []).append('Сообщение отправлено!')
                log_admin_action(admin_id, 'private_message', f'Sent message to user {target_user}')
            except Exception as e:
                session.setdefault('flashed_messages', []).append(f'Ошибка отправки: {str(e)}')
            raise web.HTTPFound(f'/admin/{admin_id}')
        
        template = template_env.get_template('admin_dashboard.html')
        return web.Response(
            text=template.render(
                private_message=True,
                admin_id=admin_id,
                get_flashed_messages=get_flashed_messages
            ),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка обработки личного сообщения: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Обработчик статистики
async def user_stats(request):
    try:
        admin_id = await check_auth(request)
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        # Общая статистика
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_subscribed = 1")
        total_subscribers = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        total_banned = c.fetchone()[0]
        
        # Новые пользователи
        today = datetime.utcnow().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(*) FROM users WHERE date(joined_at) = ?", (today,))
        new_today = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE joined_at >= date('now', '-7 days')")
        new_week = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE joined_at >= date('now', '-30 days')")
        new_month = c.fetchone()[0]
        
        # Статистика канала
        try:
            channel_subscribers = await bot.get_chat_member_count(chat_id=CHANNEL_ID)
        except Exception as e:
            logger.error(f"Ошибка получения подписчиков канала: {e}")
            channel_subscribers = 0
        
        # Данные для графика
        c.execute("""
            SELECT strftime('%Y-%m', joined_at) AS month, COUNT(*) AS count
            FROM users
            WHERE joined_at >= date('now', '-3 months')
            GROUP BY month
            ORDER BY month
        """)
        chart_data = c.fetchall()
        labels = [row[0] for row in chart_data]
        data = [row[1] for row in chart_data]
        
        conn.close()
        
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
        
        template = template_env.get_template('admin_dashboard.html')
        return web.Response(
            text=template.render(
                stats_page=True,
                admin_id=admin_id,
                stats=stats,
                get_flashed_messages=get_flashed_messages
            ),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка обработки статистики: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Обработчик управления пользователями
async def user_management(request):
    try:
        admin_id = await check_auth(request)
        session = await get_session(request)
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        if request.method == 'POST':
            data = await request.post()
            action = data.get('action')
            selected_users = data.getlist('selected_users') or [data.get('user_id')]
            
            if action == 'ban':
                c.executemany("UPDATE users SET is_banned = 1 WHERE user_id = ?", [(uid,) for uid in selected_users])
                log_admin_action(admin_id, 'ban_users', f'Banned users: {", ".join(selected_users)}')
            elif action == 'unban':
                c.executemany("UPDATE users SET is_banned = 0 WHERE user_id = ?", [(uid,) for uid in selected_users])
                log_admin_action(admin_id, 'unban_users', f'Unbanned users: {", ".join(selected_users)}')
            elif action == 'make_admin':
                c.executemany("UPDATE users SET is_admin = 1 WHERE user_id = ?", [(uid,) for uid in selected_users])
                log_admin_action(admin_id, 'make_admin', f'Made admin: {", ".join(selected_users)}')
            elif action == 'remove_admin':
                c.executemany("UPDATE users SET is_admin = 0 WHERE user_id = ?", [(uid,) for uid in selected_users])
                log_admin_action(admin_id, 'remove_admin', f'Removed admin: {", ".join(selected_users)}')
            
            conn.commit()
            session.setdefault('flashed_messages', []).append(f'Действие {action} выполнено!')
            raise web.HTTPFound(f'/admin/{admin_id}')
        
        # Фильтры и поиск
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
        
        c.execute(query, params)
        users = c.fetchall()
        conn.close()
        
        template = template_env.get_template('admin_dashboard.html')
        return web.Response(
            text=template.render(
                user_management=True,
                admin_id=admin_id,
                users=users,
                search_query=search_query,
                filter_subscribed=filter_subscribed,
                filter_admin=filter_admin,
                filter_banned=filter_banned,
                get_flashed_messages=get_flashed_messages
            ),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка обработки управления пользователями: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Обработчик логов активности
async def activity_logs(request):
    try:
        admin_id = await check_auth(request)
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT log_id, admin_id, action, details, timestamp FROM activity_logs ORDER BY timestamp DESC LIMIT 100")
        logs = c.fetchall()
        conn.close()
        
        template = template_env.get_template('admin_dashboard.html')
        return web.Response(
            text=template.render(
                activity_logs=True,
                admin_id=admin_id,
                logs=logs,
                get_flashed_messages=get_flashed_messages
            ),
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"Ошибка обработки логов активности: {e}")
        return web.Response(status=500, text="Internal Server Error")

# Проверка подписки на канал
async def check_subscription(user_id):
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
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
        
        # Сохранение пользователя в базе данных
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, first_name, last_name))
        conn.commit()
        conn.close()
        
        # Проверка подписки
        is_subscribed = await check_subscription(user_id)
        if is_subscribed:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("UPDATE users SET is_subscribed = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
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
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("UPDATE users SET is_subscribed = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            await callback_query.message.edit_text("Спасибо за подписку! Теперь вы можете использовать бот.")
        else:
            await callback_query.message.edit_text(
                "Вы ещё не подписаны на канал. Пожалуйста, подпишитесь!",
                reply_markup=callback_query.message.reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        await callback_query.message.edit_text("Произошла ошибка. Попробуйте позже.")

# Настройка вебхука
async def on_startup(app):
    try:
        logger.info("Установка вебхука...")
        webhook = await bot.get_webhook_info()
        if webhook.url != WEBHOOK_URL:
            await bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"Вебхук установлен на {WEBHOOK_URL}")
        else:
            logger.info("Вебхук уже установлен")
        init_db()
    except Exception as e:
        logger.error(f"Ошибка при запуске приложения: {e}")

async def on_shutdown(app):
    try:
        logger.info("Остановка бота...")
        await bot.delete_webhook()
        await bot.session.close()
    except Exception as e:
        logger.error(f"Ошибка при остановке приложения: {e}")

# Добавление маршрутов
app.router.add_get('/', admin_panel)
app.router.add_post('/', login_handler)
app.router.add_get('/admin/{admin_id}', admin_dashboard)
app.router.add_get('/logout', logout_handler)
app.router.add_route('*', '/admin/{admin_id}/edit_welcome', edit_welcome)
app.router.add_route('*', '/admin/{admin_id}/broadcast', broadcast)
app.router.add_route('*', '/admin/{admin_id}/private_message', private_message)
app.router.add_route('*', '/admin/{admin_id}/user_stats', user_stats)
app.router.add_route('*', '/admin/{admin_id}/user_management', user_management)
app.router.add_route('*', '/admin/{admin_id}/activity_logs', activity_logs)

# Настройка aiogram с aiohttp
request_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
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
