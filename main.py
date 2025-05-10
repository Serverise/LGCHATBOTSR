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
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)  # Убрали DefaultBotProperties
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
@dp.message(lambda message: message.text == '/start')
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

    if await check_subscription(user_id):
        try:
            cursor.execute('SELECT welcome_message FROM channels LIMIT 1')
            welcome_msg = cursor.fetchone()
            msg = welcome_msg[0] if welcome_msg and welcome_msg[0] else "Спасибо за подписку! Вы добавлены в канал."
            await message.answer(msg)
        except Exception as e:
            logger.error(f"Ошибка базы данных при получении приветственного сообщения: {str(e)}")
            await message.answer("Произошла ошибка. Попробуйте позже.")
    else:
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text="Подписаться", url=CHANNEL_LINK),
            types.InlineKeyboardButton(text="Проверить подписку", callback_data="check_subscription")
        ]])
        await message.answer(
            "Пожалуйста, подпишитесь на канал, чтобы продолжить.",
            reply_markup=keyboard
        )

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
        return result and result[0]
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
                if result and result[0]:
                    session['admin_id'] = admin_id
                    log_admin_action(admin_id, "Вход", "Админ вошел в систему")
                    return redirect(url_for('admin_dashboard', admin_id=admin_id))
                else:
                    flash('У вас нет прав администратора.')
            else:
                flash('Неверный пароль.')
        except ValueError:
            flash('Введите корректный ID администратора.')
        except Exception as e:
            logger.error(f"Ошибка базы данных при проверке админа {admin_id}: {str(e)}")
            flash('Произошла ошибка. Попробуйте позже.')
    return render_template('admin_dashboard.html', login_page=True)

@app.route('/admin/<int:admin_id>')
def admin_dashboard(admin_id):
    if not check_admin_auth(admin_id):
        return redirect(url_for('admin_panel'))
    return render_template('admin_dashboard.html', admin_id=admin_id, dashboard=True)

@app.route('/admin/<int:admin_id>/edit_welcome', methods=['GET', 'POST'])
def edit_welcome(admin_id):
    if not check_admin_auth(admin_id):
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        welcome_msg = request.form.get('welcome_message')
        if welcome_msg:
            try:
                cursor.execute('UPDATE channels SET welcome_message = ? WHERE rowid = 1', (welcome_msg,))
                conn.commit()
                log_admin_action(admin_id, "Обновление приветствия", f"Обновлено приветственное сообщение: {welcome_msg[:50]}...")
                flash('Приветственное сообщение обновлено!')
                return redirect(url_for('admin_dashboard', admin_id=admin_id))
            except Exception as e:
                logger.error(f"Ошибка базы данных при обновлении приветствия: {str(e)}")
                flash('Ошибка при сохранении сообщения.')
        else:
            flash('Введите текст сообщения.')

    try:
        cursor.execute('SELECT welcome_message FROM channels LIMIT 1')
        current_msg = cursor.fetchone()
        current_msg = current_msg[0] if current_msg else ''
        return render_template('admin_dashboard.html', admin_id=admin_id, edit_welcome=True, current_msg=current_msg)
    except Exception as e:
        logger.error(f"Ошибка базы данных при получении текущего сообщения: {str(e)}")
        flash('Произошла ошибка. Попробуйте позже.')
        return redirect(url_for('admin_dashboard', admin_id=admin_id))

@app.route('/admin/<int:admin_id>/broadcast', methods=['GET', 'POST'])
async def broadcast(admin_id):
    if not check_admin_auth(admin_id):
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        broadcast_msg = request.form.get('broadcast_message')
        if broadcast_msg:
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
                
                log_admin_action(admin_id, "Рассылка", f"Отправлено {success} пользователям, не удалось: {failed}")
                flash(f'Рассылка завершена! Успешно: {success}, Не удалось: {failed}')
                return redirect(url_for('admin_dashboard', admin_id=admin_id))
            except Exception as e:
                logger.error(f"Ошибка при рассылке: {str(e)}")
                flash('Ошибка при рассылке.')
        else:
            flash('Введите текст сообщения.')

    return render_template('admin_dashboard.html', admin_id=admin_id, broadcast=True)

@app.route('/admin/<int:admin_id>/private_message', methods=['GET', 'POST'])
async def private_message(admin_id):
    if not check_admin_auth(admin_id):
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        target_user = request.form.get('target_user')
        private_msg = request.form.get('private_message')
        try:
            target_user = int(target_user)
            if private_msg:
                cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (target_user,))
                user = cursor.fetchone()
                if user and user[0] == 0:
                    if await send_message_safe(target_user, private_msg):
                        log_admin_action(admin_id, "Личное сообщение", f"Отправлено пользователю {target_user}")
                        flash(f'Сообщение отправлено пользователю {target_user}')
                    else:
                        flash(f'Ошибка отправки сообщения пользователю {target_user}.')
                else:
                    flash('Пользователь не найден или заблокирован.')
                return redirect(url_for('admin_dashboard', admin_id=admin_id))
            else:
                flash('Введите текст сообщения.')
        except ValueError:
            flash('Введите корректный ID пользователя.')
        except Exception as e:
            logger.error(f"Ошибка отправки личного сообщения пользователю {target_user}: {str(e)}")
            flash('Произошла ошибка. Попробуйте позже.')

    return render_template('admin_dashboard.html', admin_id=admin_id, private_message=True)

@app.route('/admin/<int:admin_id>/stats')
def user_stats(admin_id):
    if not check_admin_auth(admin_id):
        return redirect(url_for('admin_panel'))

    try:
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) = date("now")')
        new_today = cursor.fetchone()[0]
        
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) >= ?', (week_ago,))
        new_week = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE date(join_date) >= ?', (month_ago,))
        new_month = cursor.fetchone()[0]
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        chat = loop.run_until_complete(bot.get_chat(CHANNEL_ID))
        total_subscribers = chat.members_count if hasattr(chat, 'members_count') else 0
        loop.close()
        
        today = datetime.now().date()
        cursor.execute('''
            SELECT COUNT(*) 
            FROM users 
            WHERE is_subscribed = 1 
            AND date(last_subscription_change) = ?
        ''', (today.strftime("%Y-%m-%d"),))
        subscribed_today = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(*) 
            FROM users 
            WHERE is_subscribed = 0 
            AND date(last_subscription_change) = ?
        ''', (today.strftime("%Y-%m-%d"),))
        unsubscribed_today = cursor.fetchone()[0]
        
        chart_data = {
            'labels': ['Сегодня', 'На этой неделе', 'В этом месяце'],
            'datasets': [{
                'label': 'Новые пользователи',
                'data': [new_today or 0, new_week or 0, new_month or 0],
                'backgroundColor': 'rgba(217, 119, 6, 0.6)',
                'borderColor': 'rgba(217, 119, 6, 1)',
                'borderWidth': 1
            }]
        }
        
        stats = {
            'total_users': total_users or 0,
            'new_today': new_today or 0,
            'new_week': new_week or 0,
            'new_month': new_month or 0,
            'total_subscribers': total_subscribers or 0,
            'subscribed_today': subscribed_today or 0,
            'unsubscribed_today': unsubscribed_today or 0,
            'chart_data': chart_data
        }
        log_admin_action(admin_id, "Просмотр статистики", "Перешел на страницу статистики")
        return render_template('admin_dashboard.html', admin_id=admin_id, stats=stats, stats_page=True)
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {str(e)}")
        flash('Произошла ошибка при получении статистики. Попробуйте позже.')
        return redirect(url_for('admin_dashboard', admin_id=admin_id))

@app.route('/admin/<int:admin_id>/users', methods=['GET', 'POST'])
def user_management(admin_id):
    if not check_admin_auth(admin_id):
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id')
        try:
            user_id = int(user_id)
            if action == 'ban':
                cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
                log_admin_action(admin_id, "Блокировка пользователя", f"Заблокирован пользователь {user_id}")
                flash(f'Пользователь {user_id} заблокирован.')
            elif action == 'unban':
                cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
                log_admin_action(admin_id, "Разблокировка пользователя", f"Разблокирован пользователь {user_id}")
                flash(f'Пользователь {user_id} разблокирован.')
            elif action == 'make_admin':
                cursor.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (user_id,))
                log_admin_action(admin_id, "Назначение админа", f"Пользователь {user_id} назначен админом")
                flash(f'Пользователь {user_id} назначен администратором.')
            elif action == 'remove_admin':
                cursor.execute('UPDATE users SET is_admin = 0 WHERE user_id = ?', (user_id,))
                log_admin_action(admin_id, "Снятие админа", f"С пользователя {user_id} сняты права админа")
                flash(f'Пользователь {user_id} больше не администратор.')
            conn.commit()
        except ValueError:
            flash('Неверный ID пользователя.')
        except Exception as e:
            logger.error(f"Ошибка управления пользователем {user_id}: {str(e)}")
            flash('Произошла ошибка. Попробуйте позже.')

    try:
        cursor.execute('SELECT user_id, username, first_name, last_name, join_date, is_subscribed, is_admin, is_banned FROM users')
        users = cursor.fetchall()
        log_admin_action(admin_id, "Просмотр пользователей", "Перешел на страницу управления пользователями")
        return render_template('admin_dashboard.html', admin_id=admin_id, users=users, user_management=True)
    except Exception as e:
        logger.error(f"Ошибка получения пользователей: {str(e)}")
        flash('Произошла ошибка при получении списка пользователей.')
        return redirect(url_for('admin_dashboard', admin_id=admin_id))

@app.route('/admin/<int:admin_id>/logs')
def activity_logs(admin_id):
    if not check_admin_auth(admin_id):
        return redirect(url_for('admin_panel'))

    try:
        cursor.execute('SELECT id, admin_id, action, details, timestamp FROM activity_logs ORDER BY timestamp DESC LIMIT 100')
        logs = cursor.fetchall()
        log_admin_action(admin_id, "Просмотр логов", "Перешел на страницу логов активности")
        return render_template('admin_dashboard.html', admin_id=admin_id, logs=logs, activity_logs=True)
    except Exception as e:
        logger.error(f"Ошибка получения логов: {str(e)}")
        flash('Произошла ошибка при получении логов.')
        return redirect(url_for('admin_dashboard', admin_id=admin_id))

@app.route('/logout')
def logout():
    admin_id = session.get('admin_id')
    if admin_id:
        log_admin_action(admin_id, "Выход", "Админ вышел из системы")
    session.pop('admin_id', None)
    return redirect(url_for('admin_panel'))

# Инициализация базы данных
async def on_startup():
    try:
        cursor.execute('SELECT COUNT(*) FROM channels')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO channels (channel_id, title, welcome_message) VALUES (?, ?, ?)', 
                          (-1002587647993, "Legeris Channel", "Добро пожаловать в наш канал! Спасибо за подписку."))
            conn.commit()
        
        cursor.execute('INSERT OR IGNORE INTO users (user_id, is_admin) VALUES (?, ?)', (ADMIN_ID, 1))
        conn.commit()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {str(e)}")

# Запуск бота
def start_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(on_startup())
        loop.run_until_complete(dp.start_polling(bot, skip_updates=True))
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")
    finally:
        loop.close()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
