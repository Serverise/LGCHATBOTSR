import os
import logging
import sqlite3
import asyncio
from aiohttp import web
from aiohttp_session import setup, get_session, SimpleCookieStorage
from jinja2 import Environment, FileSystemLoader
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройка Jinja2
template_env = Environment(loader=FileSystemLoader('templates'))

# Инициализация базы данных SQLite
def init_db():
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
    # Добавление тестового админа
    c.execute("INSERT OR IGNORE INTO admins (admin_id, password) VALUES (?, ?)",
              ("5033892308", "admin123"))
    # Добавление начального приветственного сообщения
    c.execute("INSERT OR IGNORE INTO settings (id, welcome_message) VALUES (?, ?)",
              (1, "Добро пожаловать в бот!"))
    conn.commit()
    conn.close()
    logger.info("Админ 5033892308 успешно добавлен в базу данных")

# Инициализация бота и диспетчера
BOT_TOKEN = os.getenv('BOT_TOKEN', 'your-bot-token')  # Укажите токен в переменной окружения
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://lgchatbotsr.onrender.com') + WEBHOOK_PATH
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Создание приложения aiohttp
app = web.Application()

# Настройка сессий
setup(app, SimpleCookieStorage())

# Функция для получения флэш-сообщений
async def get_flashed_messages(request):
    session = await get_session(request)
    messages = session.pop('flashed_messages', [])
    return messages

# Проверка авторизации
async def check_auth(request):
    session = await get_session(request)
    admin_id = session.get('admin_id')
    if not admin_id:
        session.setdefault('flashed_messages', []).append('Требуется авторизация!')
        raise web.HTTPFound('/')
    return admin_id

# Обработчик маршрута для страницы логина
async def admin_panel(request):
    template = template_env.get_template('admin_login.html')
    logger.info("Обращение к маршруту /")
    return web.Response(
        text=template.render(
            login_page=True,
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Обработчик логина
async def login_handler(request):
    session = await get_session(request)
    data = await request.post()
    admin_id = data.get('admin_id')
    password = data.get('password')
    
    # Проверка в базе данных
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT password FROM admins WHERE admin_id = ?", (admin_id,))
    result = c.fetchone()
    conn.close()
    
    if result and result[0] == password:  # В продакшене используйте хеширование
        session['admin_id'] = admin_id
        session.setdefault('flashed_messages', []).append('Успешный вход!')
        raise web.HTTPFound(f'/admin/{admin_id}')
    else:
        session.setdefault('flashed_messages', []).append('Неверный ID или пароль!')
        raise web.HTTPFound('/')

# Обработчик админ-панели
async def admin_dashboard(request):
    admin_id = await check_auth(request)
    template = template_env.get_template('admin_dashboard.html')
    logger.info(f"Обращение к маршруту /admin/{admin_id}")
    return web.Response(
        text=template.render(
            dashboard=True,
            admin_id=admin_id,
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Обработчик выхода
async def logout_handler(request):
    session = await get_session(request)
    session.clear()
    session.setdefault('flashed_messages', []).append('Вы вышли из системы!')
    raise web.HTTPFound('/')

# Обработчик редактирования приветственного сообщения
async def edit_welcome(request):
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
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Обработчик рассылки
async def broadcast(request):
    admin_id = await check_auth(request)
    session = await get_session(request)
    
    if request.method == 'POST':
        data = await request.post()
        broadcast_message = data.get('broadcast_message')
        # Заглушка: здесь должна быть логика рассылки
        session.setdefault('flashed_messages', []).append('Рассылка отправлена!')
        raise web.HTTPFound(f'/admin/{admin_id}')
    
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(
        text=template.render(
            broadcast=True,
            admin_id=admin_id,
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Обработчик личных сообщений
async def private_message(request):
    admin_id = await check_auth(request)
    session = await get_session(request)
    
    if request.method == 'POST':
        data = await request.post()
        target_user = data.get('target_user')
        private_message = data.get('private_message')
        try:
            await bot.send_message(chat_id=target_user, text=private_message)
            session.setdefault('flashed_messages', []).append('Сообщение отправлено!')
        except Exception as e:
            session.setdefault('flashed_messages', []).append(f'Ошибка отправки: {str(e)}')
        raise web.HTTPFound(f'/admin/{admin_id}')
    
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(
        text=template.render(
            private_message=True,
            admin_id=admin_id,
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Обработчик статистики
async def user_stats(request):
    admin_id = await check_auth(request)
    template = template_env.get_template('admin_dashboard.html')
    # Пример данных статистики
    stats = {
        'total_users': 100,
        'new_today': 5,
        'new_week': 20,
        'new_month': 50,
        'total_subscribers': 80,
        'subscribed_today': 3,
        'unsubscribed_today': 1,
        'channel_subscribers': 75,
        'chart_data': {
            'labels': ['Jan', 'Feb', 'Mar'],
            'datasets': [{'label': 'New Users', 'data': [10, 20, 30]}]
        }
    }
    return web.Response(
        text=template.render(
            stats_page=True,
            admin_id=admin_id,
            stats=stats,
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Обработчик управления пользователями
async def user_management(request):
    admin_id = await check_auth(request)
    session = await get_session(request)
    
    if request.method == 'POST':
        data = await request.post()
        action = data.get('action')
        session.setdefault('flashed_messages', []).append(f'Действие {action} выполнено!')
        raise web.HTTPFound(f'/admin/{admin_id}')
    
    users = [
        (123, '@user1', 'John', 'Doe', '2023-01-01', True, False, False),
        (456, '@user2', 'Jane', 'Doe', '2023-02-01', False, True, True)
    ]
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(
        text=template.render(
            user_management=True,
            admin_id=admin_id,
            users=users,
            search_query='',
            filter_subscribed='',
            filter_admin='',
            filter_banned='',
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Обработчик логов активности
async def activity_logs(request):
    admin_id = await check_auth(request)
    logs = [
        (1, admin_id, 'login', 'Logged in', '2023-05-10 12:00:00'),
        (2, admin_id, 'update_welcome', 'Updated welcome message', '2023-05-10 12:01:00')
    ]
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(
        text=template.render(
            activity_logs=True,
            admin_id=admin_id,
            logs=logs,
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Telegram-обработчик команды /start
@dp.message(Command('start'))
async def cmd_start(message):
    # Создание клавиатуры с корректным inline_keyboard
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть админ-панель", url="https://lgchatbotsr.onrender.com")]
        ]
    )
    await message.answer("Привет! Это ваш бот.", reply_markup=keyboard)

# Настройка вебхука
async def on_startup():
    logger.info("Установка вебхука...")
    webhook = await bot.get_webhook_info()
    if webhook.url != WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Вебхук установлен на {WEBHOOK_URL}")
    else:
        logger.info("Вебхук уже установлен")
    init_db()

async def on_shutdown():
    logger.info("Остановка бота...")
    await bot.delete_webhook()
    await bot.session.close()

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
    port = int(os.getenv('PORT', 8080))  # Порт для Render
    web.run_app(app, port=port)
