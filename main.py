import logging
import sqlite3
from datetime import datetime, timedelta
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
import jinja2
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация бота
API_TOKEN = '7731278147:AAGNBi8Td-kSWr0Hhxdh0r46fXKzVsI0S2w'
CHANNEL_ID = '-1002587647993'
CHANNEL_LINK = 'https://t.me/+KZeOjH5orpRiNjgy'
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"https://lgchatbotsr.onrender.com{WEBHOOK_PATH}"

# Инициализация бота
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
        logger.info(f"Статус пользователя {user_id}: {member.status}, Подписан: {is_subscribed}")
        
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

# Получение количества подписчиков канала
async def get_channel_subscribers() -> int:
    try:
        chat = await bot.get_chat(CHANNEL_ID)
        subscriber_count = chat.members_count
        logger.info(f"Количество подписчиков в канале {CHANNEL_ID}: {subscriber_count}")
        return subscriber_count
    except Exception as e:
        logger.error(f"Ошибка получения количества подписчиков: {str(e)}")
        return 0

# Безопасная отправка сообщения
async def send_message_safe(chat_id: int, text: str) -> bool:
    try:
        await bot.send_message(chat_id, text)
        logger.info(f"Сообщение отправлено пользователю {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения пользователю {chat_id}: {str(e)}")
        return False

# Логирование действий админа
def log_admin_action(admin_id, action, details):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO activity_logs (admin_id, action, details, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (admin_id, action, details, timestamp))
    conn.commit()
    logger.info(f"Действие админа {admin_id}: {action} - {details}")

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
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_subscribed = 1')
            total_subscribers = cursor.fetchone()[0]
            channel_subscribers = await get_channel_subscribers()
            stats = f"📊 Статистика пользователей:\n\nВсего пользователей: {total_users}\nНовых сегодня: {new_today}\nПодписчиков: {total_subscribers}\nПодписчиков в канале: {channel_subscribers}"
            await bot.send_message(user_id, stats)
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {str(e)}")
            await bot.send_message(user_id, "Ошибка при получении статистики. Попробуйте позже.")

# Обработка ввода приветственного сообщения
@dp.message(StateFilter(Form.welcome_message))
async def process_welcome_message(message: types.Message, state: FSMContext):
    welcome_msg = message.text
    user_id = message.from_user.id
    try:
        cursor.execute('UPDATE channels SET welcome_message = ? WHERE rowid = 1', (welcome_msg,))
        conn.commit()
        log_admin_action(user_id, "edit_welcome", f"Обновлено приветственное сообщение: {welcome_msg}")
        await state.finish()
        await message.answer("Приветственное сообщение успешно обновлено!")
    except Exception as e:
        logger.error(f"Ошибка при обновлении приветственного сообщения: {str(e)}")
        await message.answer("Ошибка при обновлении сообщения. Попробуйте позже.")

# Обработка ввода сообщения для рассылки
@dp.message(StateFilter(Form.broadcast_message))
async def process_broadcast(message: types.Message, state: FSMContext):
    broadcast_msg = message.text
    user_id = message.from_user.id
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
        log_admin_action(user_id, "broadcast", f"Рассылка: Успешно: {success}, Не удалось: {failed}")
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
    user_id = message.from_user.id
    data = await state.get_data()
    target_user = data.get('target_user')
    if await send_message_safe(target_user, private_msg):
        log_admin_action(user_id, "private_message", f"Сообщение отправлено пользователю {target_user}: {private_msg}")
        await message.answer(f"Сообщение успешно отправлено пользователю {target_user}")
    else:
        log_admin_action(user_id, "private_message_failed", f"Не удалось отправить сообщение пользователю {target_user}")
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

# Настройка сессий
sessions = {}

# Проверка авторизации админа
def check_admin_auth(admin_id):
    if admin_id not in sessions:
        return False
    try:
        cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (admin_id,))
        result = cursor.fetchone()
        return result and result[0] == 1
    except Exception as e:
        logger.error(f"Ошибка базы данных при проверке админа {admin_id}: {str(e)}")
        return False

# Инициализация Jinja2 для рендеринга шаблонов
template_loader = jinja2.FileSystemLoader(searchpath="templates")
template_env = jinja2.Environment(loader=template_loader)

# Обработчики маршрутов
async def admin_panel(request):
    logger.info("Обращение к маршруту /")
    if request.method == 'POST':
        data = await request.post()
        admin_id = data.get('admin_id')
        password = data.get('password')
        try:
            admin_id = int(admin_id)
            logger.info(f"Попытка входа с admin_id={admin_id}")
            if password == 'LegerisKEY-738197481275618273858173':
                cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (admin_id,))
                result = cursor.fetchone()
                if result and result[0] == 1:
                    sessions[admin_id] = True
                    log_admin_action(admin_id, "login", "Успешный вход в админ-панель")
                    raise web.HTTPFound(f'/admin/{admin_id}')
                return web.Response(text="У вас нет прав администратора.", status=403)
            return web.Response(text="Неверный пароль.", status=401)
        except ValueError:
            return web.Response(text="Введите корректный ID администратора.", status=400)
        except Exception as e:
            logger.error(f"Ошибка базы данных при проверке админа {admin_id}: {str(e)}")
            return web.Response(text="Произошла ошибка. Попробуйте позже.", status=500)
    template = template_env.get_template('admin_login.html')
    return web.Response(text=template.render(login_page=True), content_type='text/html')

async def admin_dashboard(request):
    admin_id = int(request.match_info['admin_id'])
    logger.info(f"Обращение к маршруту /admin/{admin_id}")
    if not check_admin_auth(admin_id):
        logger.warning(f"Неавторизованный доступ к /admin/{admin_id}")
        raise web.HTTPFound('/')
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(text=template.render(admin_id=admin_id, dashboard=True), content_type='text/html')

async def edit_welcome(request):
    admin_id = int(request.match_info['admin_id'])
    logger.info(f"Обращение к маршруту /admin/{admin_id}/edit_welcome")
    if not check_admin_auth(admin_id):
        logger.warning(f"Неавторизованный доступ к /admin/{admin_id}/edit_welcome")
        raise web.HTTPFound('/')
    if request.method == 'POST':
        data = await request.post()
        welcome_message = data.get('welcome_message')
        cursor.execute('UPDATE channels SET welcome_message = ? WHERE rowid = 1', (welcome_message,))
        conn.commit()
        log_admin_action(admin_id, "edit_welcome", f"Обновлено приветственное сообщение: {welcome_message}")
        raise web.HTTPFound(f'/admin/{admin_id}/edit_welcome')
    cursor.execute('SELECT welcome_message FROM channels LIMIT 1')
    current_msg = cursor.fetchone()
    current_msg = current_msg[0] if current_msg and current_msg[0] else "Добро пожаловать в наш канал!"
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(text=template.render(admin_id=admin_id, edit_welcome=True, current_msg=current_msg), content_type='text/html')

async def broadcast(request):
    admin_id = int(request.match_info['admin_id'])
    logger.info(f"Обращение к маршруту /admin/{admin_id}/broadcast")
    if not check_admin_auth(admin_id):
        logger.warning(f"Неавторизованный доступ к /admin/{admin_id}/broadcast")
        raise web.HTTPFound('/')
    if request.method == 'POST':
        data = await request.post()
        broadcast_message = data.get('broadcast_message')
        cursor.execute('SELECT user_id FROM users WHERE is_banned = 0 AND is_subscribed = 1')
        users = cursor.fetchall()
        success = 0
        failed = 0
        for user in users:
            if await send_message_safe(user[0], broadcast_message):
                success += 1
            else:
                failed += 1
        log_admin_action(admin_id, "broadcast", f"Рассылка: Успешно: {success}, Не удалось: {failed}")
        raise web.HTTPFound(f'/admin/{admin_id}/broadcast')
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(text=template.render(admin_id=admin_id, broadcast=True), content_type='text/html')

async def private_message(request):
    admin_id = int(request.match_info['admin_id'])
    logger.info(f"Обращение к маршруту /admin/{admin_id}/private_message")
    if not check_admin_auth(admin_id):
        logger.warning(f"Неавторизованный доступ к /admin/{admin_id}/private_message")
        raise web.HTTPFound('/')
    if request.method == 'POST':
        data = await request.post()
        target_user = data.get('target_user')
        private_msg = data.get('private_message')
        try:
            target_user = int(target_user)
            result = await send_message_safe(target_user, private_msg)
            if result:
                log_admin_action(admin_id, "private_message", f"Сообщение отправлено пользователю {target_user}: {private_msg}")
            else:
                log_admin_action(admin_id, "private_message_failed", f"Не удалось отправить сообщение пользователю {target_user}")
            raise web.HTTPFound(f'/admin/{admin_id}/private_message')
        except ValueError:
            raise web.HTTPFound(f'/admin/{admin_id}/private_message')
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(text=template.render(admin_id=admin_id, private_message=True), content_type='text/html')

async def user_stats(request):
    admin_id = int(request.match_info['admin_id'])
    logger.info(f"Обращение к маршруту /admin/{admin_id}/user_stats")
    if not check_admin_auth(admin_id):
        logger.warning(f"Неавторизованный доступ к /admin/{admin_id}/user_stats")
        raise web.HTTPFound('/')
    
    # Статистика пользователей
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) = date("now")')
    new_today = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) >= date("now", "-7 days")')
    new_week = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) >= date("now", "-30 days")')
    new_month = cursor.fetchone()[0]

    # Статистика подписок
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_subscribed = 1')
    total_subscribers = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_subscribed = 1 AND date(last_subscription_change) = date("now")')
    subscribed_today = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_subscribed = 0 AND date(last_subscription_change) = date("now")')
    unsubscribed_today = cursor.fetchone()[0]

    # Получение количества подписчиков канала
    channel_subscribers = await get_channel_subscribers()

    # Данные для графика (последние 7 дней)
    labels = []
    data = []
    for i in range(6, -1, -1):
        date = (datetime.now().date() - timedelta(days=i)).isoformat()
        cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) = ?', (date,))
        count = cursor.fetchone()[0]
        labels.append(date)
        data.append(count)

    chart_data = {
        'labels': labels,
        'datasets': [{
            'label': 'Новые пользователи',
            'data': data,
            'backgroundColor': '#d97706',
            'borderColor': '#b45309',
            'borderWidth': 1
        }]
    }

    stats = {
        'total_users': total_users,
        'new_today': new_today,
        'new_week': new_week,
        'new_month': new_month,
        'total_subscribers': total_subscribers,
        'subscribed_today': subscribed_today,
        'unsubscribed_today': unsubscribed_today,
        'channel_subscribers': channel_subscribers,
        'chart_data': chart_data
    }

    template = template_env.get_template('admin_dashboard.html')
    return web.Response(text=template.render(admin_id=admin_id, stats_page=True, stats=stats), content_type='text/html')

async def user_management(request):
    admin_id = int(request.match_info['admin_id'])
    logger.info(f"Обращение к маршруту /admin/{admin_id}/user_management")
    if not check_admin_auth(admin_id):
        logger.warning(f"Неавторизованный доступ к /admin/{admin_id}/user_management")
        raise web.HTTPFound('/')
    
    search_query = request.query.get('search', '').strip()
    filter_subscribed = request.query.get('subscribed', '')
    filter_admin = request.query.get('admin', '')
    filter_banned = request.query.get('banned', '')

    query = 'SELECT user_id, username, first_name, last_name, join_date, is_subscribed, is_admin, is_banned FROM users WHERE 1=1'
    params = []
    if search_query:
        query += ' AND (user_id LIKE ? OR username LIKE ? OR first_name LIKE ? OR last_name LIKE ?)'
        search_pattern = f'%{search_query}%'
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])
    if filter_subscribed:
        query += ' AND is_subscribed = ?'
        params.append(1 if filter_subscribed == 'yes' else 0)
    if filter_admin:
        query += ' AND is_admin = ?'
        params.append(1 if filter_admin == 'yes' else 0)
    if filter_banned:
        query += ' AND is_banned = ?'
        params.append(1 if filter_banned == 'yes' else 0)

    cursor.execute(query, params)
    users = cursor.fetchall()

    if request.method == 'POST':
        data = await request.post()
        action = data.get('action')

        if action in ['ban', 'unban', 'make_admin', 'remove_admin']:
            user_id = int(data.get('user_id'))
            if action == 'ban':
                cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
                log_admin_action(admin_id, "ban_user", f"Пользователь {user_id} заблокирован")
            elif action == 'unban':
                cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
                log_admin_action(admin_id, "unban_user", f"Пользователь {user_id} разблокирован")
            elif action == 'make_admin':
                cursor.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (user_id,))
                log_admin_action(admin_id, "make_admin", f"Пользователь {user_id} назначен администратором")
            elif action == 'remove_admin':
                cursor.execute('UPDATE users SET is_admin = 0 WHERE user_id = ?', (user_id,))
                log_admin_action(admin_id, "remove_admin", f"Пользователь {user_id} лишен прав администратора")
        elif action in ['bulk_ban', 'bulk_unban']:
            user_ids = [int(uid) for uid in data.getall('selected_users', [])]
            if action == 'bulk_ban':
                for user_id in user_ids:
                    cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
                    log_admin_action(admin_id, "ban_user", f"Пользователь {user_id} заблокирован")
            elif action == 'bulk_unban':
                for user_id in user_ids:
                    cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
                    log_admin_action(admin_id, "unban_user", f"Пользователь {user_id} разблокирован")
        
        conn.commit()
        raise web.HTTPFound(f'/admin/{admin_id}/user_management?search={search_query}&subscribed={filter_subscribed}&admin={filter_admin}&banned={filter_banned}')

    template = template_env.get_template('admin_dashboard.html')
    return web.Response(text=template.render(admin_id=admin_id, user_management=True, users=users, search_query=search_query, 
                                            filter_subscribed=filter_subscribed, filter_admin=filter_admin, 
                                            filter_banned=filter_banned), content_type='text/html')

async def activity_logs(request):
    admin_id = int(request.match_info['admin_id'])
    logger.info(f"Обращение к маршруту /admin/{admin_id}/activity_logs")
    if not check_admin_auth(admin_id):
        logger.warning(f"Неавторизованный доступ к /admin/{admin_id}/activity_logs")
        raise web.HTTPFound('/')
    
    cursor.execute('SELECT id, admin_id, action, details, timestamp FROM activity_logs ORDER BY timestamp DESC')
    logs = cursor.fetchall()
    template = template_env.get_template('admin_dashboard.html')
    return web.Response(text=template.render(admin_id=admin_id, activity_logs=True, logs=logs), content_type='text/html')

async def logout(request):
    admin_id = int(request.query.get('admin_id', 0))
    if admin_id in sessions:
        log_admin_action(admin_id, "logout", "Выход из админ-панели")
        del sessions[admin_id]
    raise web.HTTPFound('/')

# Обработчик вебхука
async def webhook_handler(request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return web.Response(status=200)

# Настройка вебхука
async def on_startup(app):
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

async def on_shutdown(app):
    logger.info("Остановка бота...")
    try:
        await bot.delete_webhook()
        await bot.session.close()
    except Exception as e:
        logger.error(f"Ошибка при остановке бота: {str(e)}")

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

# Запуск приложения
if __name__ == '__main__':
    logger.info("Запуск приложения...")
    init_db()
    
    app = web.Application()
    
    # Настройка маршрутов
    app.router.add_get('/', admin_panel)
    app.router.add_post('/', admin_panel)
    app.router.add_get('/admin/{admin_id:\d+}', admin_dashboard)
    app.router.add_get('/admin/{admin_id:\d+}/edit_welcome', edit_welcome)
    app.router.add_post('/admin/{admin_id:\d+}/edit_welcome', edit_welcome)
    app.router.add_get('/admin/{admin_id:\d+}/broadcast', broadcast)
    app.router.add_post('/admin/{admin_id:\d+}/broadcast', broadcast)
    app.router.add_get('/admin/{admin_id:\d+}/private_message', private_message)
    app.router.add_post('/admin/{admin_id:\d+}/private_message', private_message)
    app.router.add_get('/admin/{admin_id:\d+}/user_stats', user_stats)
    app.router.add_get('/admin/{admin_id:\d+}/user_management', user_management)
    app.router.add_post('/admin/{admin_id:\d+}/user_management', user_management)
    app.router.add_get('/admin/{admin_id:\d+}/activity_logs', activity_logs)
    app.router.add_get('/logout', logout)
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    
    # Регистрация событий старта и остановки
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    # Запуск сервера
    port = int(os.getenv('PORT', 8080))
    web.run_app(app, host='0.0.0.0', port=port)
