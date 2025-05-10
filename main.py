import os
import logging
from aiohttp import web
from aiohttp_session import setup, get_session, SimpleCookieStorage
from jinja2 import Environment, FileSystemLoader
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
import asyncio

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройка Jinja2
template_env = Environment(loader=FileSystemLoader('templates'))

# Инициализация бота и диспетчера
BOT_TOKEN = os.getenv('BOT_TOKEN', '7731278147:AAGNBi8Td-kSWr0Hhxdh0r46fXKzVsI0S2w')  # Укажите токен в переменной окружения на Render
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
    
    # Пример проверки (замените на реальную логику с базой данных)
    if admin_id == "5033892308" and password == "LegerisKEY-23489610917034123480152398":  # Укажите реальные credentials
        session['admin_id'] = admin_id
        session.setdefault('flashed_messages', []).append('Успешный вход!')
        raise web.HTTPFound(f'/admin/{admin_id}')
    else:
        session.setdefault('flashed_messages', []).append('Неверный ID или пароль!')
        raise web.HTTPFound('/')

# Обработчик админ-панели
async def admin_dashboard(request):
    session = await get_session(request)
    admin_id = request.match_info['admin_id']
    
    # Проверка авторизации
    if session.get('admin_id') != admin_id:
        session.setdefault('flashed_messages', []).append('Требуется авторизация!')
        raise web.HTTPFound('/')
    
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

# Пример обработчика для редактирования приветственного сообщения
async def edit_welcome(request):
    session = await get_session(request)
    admin_id = request.match_info['admin_id']
    
    if session.get('admin_id') != admin_id:
        session.setdefault('flashed_messages', []).append('Требуется авторизация!')
        raise web.HTTPFound('/')
    
    if request.method == 'POST':
        data = await request.post()
        welcome_message = data.get('welcome_message')
        # Здесь сохраните welcome_message в базу данных
        session.setdefault('flashed_messages', []).append('Приветственное сообщение обновлено!')
        raise web.HTTPFound(f'/admin/{admin_id}')
    
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(
        text=template.render(
            edit_welcome=True,
            admin_id=admin_id,
            current_msg="Текущее приветственное сообщение",  # Замените на данные из БД
            get_flashed_messages=lambda: get_flashed_messages(request)
        ),
        content_type='text/html'
    )

# Пример Telegram-обработчика
from aiogram.filters import Command
@dp.message(Command('start'))
async def cmd_start(message):
    await message.answer("Привет! Это ваш бот.")

# Настройка вебхука
async def on_startup():
    logger.info("Установка вебхука...")
    webhook = await bot.get_webhook_info()
    if webhook.url != WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info("Вебхук установлен")
    else:
        logger.info("Вебхук уже установлен")

async def on_shutdown():
    logger.info("Остановка приложения...")
    await bot.delete_webhook()
    await bot.session.close()

# Добавление маршрутов
app.router.add_get('/', admin_panel)
app.router.add_post('/', login_handler)
app.router.add_get('/admin/{admin_id}', admin_dashboard)
app.router.add_get('/logout', logout_handler)
app.router.add_route('*', '/admin/{admin_id}/edit_welcome', edit_welcome)

# Настройка aiogram с aiohttp
request_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
request_handler.register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)

# Регистрация хуков жизненного цикла
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# Запуск приложения
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))  # Используем PORT из окружения Render
    web.run_app(app, port=port)
