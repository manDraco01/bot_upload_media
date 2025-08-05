#Рабочий бот , без загрузки файлов.
# тест git
# 123
import logging
import os
import csv
import random
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler
)
import asyncio
import platform
import aiosqlite
from datetime import datetime

from db import (
    init_db,
    upsert_user,
    is_admin,
    add_admin,
    log_upload,
    get_user_uploads_count,
    get_upload_log,
    get_upload_stats,
    get_all_users
)

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

UPLOADS_LOG_FILE = "uploads_log.csv"  # Файл для хранения данных о загрузках

# Настройка логов
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

#LOCAL_API_URL = "http://localhost:8081"  # URL вашего локального API сервера
TOKEN = "11111"  # Ваш токен бота
DELETE_STATE = 3
PAGE_SIZE = 5
DELETE_CONVERSATION_TIMEOUT = 300

DB_PATH = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            access TEXT,
            first_seen TEXT,
            last_seen TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            username TEXT,
            file_name TEXT,
            file_type TEXT,
            timestamp TEXT
        )
        """)
        await db.commit()

# Конфигурация
PHOTO_ALBUM_LINK = "url" #Ваша ссылка на альбом
MEDIA_FOLDER = "/Фото"
ALLOWED_MIME_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi"
}


async def show_uploads_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает лог загрузок (только для админов)"""
    if update.effective_user.id not in await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для админов!")
        return

    try:
        if not os.path.exists(UPLOADS_LOG_FILE):
            await update.message.reply_text("Лог загрузок пуст.")
            return

        with open(UPLOADS_LOG_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            data = list(reader)

        if not data:
            await update.message.reply_text("Лог загрузок пуст.")
            return

        # Подсчёт общего количества загрузок
        total_uploads = len(data)

        # Подсчёт уникальных пользователей
        unique_users = len({row[0] for row in data})

        # Формируем сообщение
        message = (
            f"📊 Общая статистика загрузок:\n"
            f"• Всего загрузок: {total_uploads}\n"
            f"• Уникальных пользователей: {unique_users}\n\n"
            f"Последние 10 загрузок:\n\n"
        )

        for row in data[-10:]:
            message += (
                f"👤 {row[1]} (@{row[2]})\n"
                f"📁 {row[3]} ({row[4]})\n"
                f"🕒 {row[5]}\n\n"
            )

        await update.message.reply_text(message)

    except Exception as e:
        logger.error(f"Ошибка при чтении лога загрузок: {e}")
        await update.message.reply_text("❌ Ошибка при чтении лога загрузок")


def get_user_uploads_count(user_id: int) -> int:
    """Возвращает количество загруженных файлов пользователем"""
    try:
        if not os.path.exists(UPLOADS_LOG_FILE):
            return 0

        with open(UPLOADS_LOG_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Пропускаем заголовки
            return sum(1 for row in reader if int(row[0]) == user_id)
    except Exception as e:
        logger.error(f"Ошибка при чтении лога загрузок: {e}")
        return 0


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        file_type = ""
        content_type = ""

        # Определяем тип контента
        if update.message.document:
            media = update.message.document
            mime_type = media.mime_type
            file_size = media.file_size
            original_name = media.file_name or f"document_{update.message.id}"
            file_type = "document"
            content_type = "документ"
        elif update.message.video:
            media = update.message.video
            mime_type = media.mime_type
            file_size = media.file_size
            original_name = f"video_{update.message.id}"
            file_type = "video"
            content_type = "видео"
        elif update.message.photo:
            media = update.message.photo[-1]
            mime_type = "image/jpeg"
            file_size = media.file_size
            original_name = f"photo_{update.message.id}"
            file_type = "photo"
            content_type = "фото"
        else:
            await update.message.reply_text("❌ Неподдерживаемый тип файла")
            return

        # Проверяем MIME-тип
        if mime_type not in ALLOWED_MIME_TYPES:
            allowed_types = "\n".join([f"- {t}" for t in ALLOWED_MIME_TYPES.keys()])
            await update.message.reply_text(
                f"❌ Неподдерживаемый формат файла. Разрешенные типы:\n{allowed_types}"
            )
            return

        # Увеличиваем максимальный размер до 50MB
        MAX_SIZE = 1000 * 1024 * 1024  # 50MB
        if file_size > MAX_SIZE:
            await update.message.reply_text(
                f"❌ Файл слишком большой ({file_size / 1024 / 1024:.1f} MB). "
                f"Максимальный размер: {MAX_SIZE / 1024 / 1024} MB"
            )
            return

        # Отправляем уведомление о начале загрузки
        progress_message = await update.message.reply_text(
            f"⏳ Начинаю загрузку {content_type} ({file_size / 1024 / 1024:.1f} MB)..."
        )

        # Получаем файл с увеличенным таймаутом
        try:
            file = await media.get_file(read_timeout=300)
        except Exception as e:
            logger.error(f"File access error: {e}")
            await progress_message.edit_text("❌ Ошибка при получении файла с серверов Telegram")
            return

        # Определяем расширение файла
        file_ext = ALLOWED_MIME_TYPES.get(mime_type, "bin")

        # Формируем новое имя файла с логином пользователя
        username_part = f"_{user.username}" if user.username else f"_{user.id}"
        base_name = os.path.splitext(original_name)[0]
        file_name = f"{base_name}{username_part}.{file_ext}"

        # Сохраняем файл
        file_path = os.path.join(MEDIA_FOLDER, file_name)
        try:
            await file.download_to_drive(file_path)

            # Логируем загрузку
            log_upload(
                user_id=user.id,
                user_name=user.full_name,
                username=user.username,
                file_name=file_name,
                file_type=file_type
            )

            await progress_message.edit_text(
                f"✅ {content_type.capitalize()} успешно сохранено!\n"
                f"▸ Размер: {file_size / 1024 / 1024:.1f} MB\n"
                f"▸ Имя файла: {file_name}\n"
                f"▸ Путь: {file_path}"
            )

            await notify_admins_about_upload(
                context=context,
                user_name=user.full_name,
                username=user.username,
                file_name=file_name,
                file_type=content_type,
                file_size=file_size,
                update=update
            )

        except Exception as e:
            logger.error(f"File save error: {e}")
            await progress_message.edit_text("❌ Ошибка при сохранении файла")
            return

    except Exception as e:
        logger.error(f"Unexpected error in handle_media: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла непредвиденная ошибка при обработке файла")


async def my_uploads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает количество загруженных файлов пользователем"""
    user = update.effective_user
    count = get_user_uploads_count(user.id)

    await update.message.reply_text(
        f"📊 Ваша статистика загрузок:\n"
        f"Всего файлов загружено: {count}"
    )

# Загрузка данных


# Инициализация данных


MESSAGE_STATE = 2

COMMANDS = {
    'menu': '📋 Меню',
    'help': 'ℹ️ Помощь',
    'foto': '📷 Фотоальбом',
    'my_uploads': '📊 Мои загрузки',
    'delete_files': '🗑 Удалить мои файлы',
    'random': '🎲 Выбрать пользователя',
    'message': '📢 Отправить текст',
    'uploads_log': '📋 Лог загрузок',
    'address': '📍 Как попасть на свадьбу'
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if user.id not in users:
        users[user.id] = {
            'name': user.full_name,
            'username': user.username,
            'access': 'admin' if user.id in await is_admin(update.effective_user.id) else 'user',
            'first_seen': now,
            'last_seen': now
        }
    else:
        users[user.id].update({
            'name': user.full_name,
            'username': user.username,
            'last_seen': now
        })
    

    keyboard = [
        [COMMANDS['help'], COMMANDS['foto']],
        [COMMANDS['my_uploads'], COMMANDS['delete_files']],[COMMANDS['address']]
    ]

    if user.id in await is_admin(update.effective_user.id):
        keyboard.append([COMMANDS['random'], COMMANDS['message']])
        keyboard.append([COMMANDS['uploads_log']])

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

    await update.message.reply_text(
        f"🌟 Добро пожаловать, {user.full_name}!\n"
        f"Ваш уровень: {'👑 Админ' if user.id in await is_admin(update.effective_user.id) else '👤 Пользователь'}\n"
        f"Этот бот предназначен для загрузки фотографий и видео со свадьбы Раниля и Гулины.\n"
        f"Подробней об функционале можете узнать по кнопке «Помощь» или /help.",
        reply_markup=reply_markup
    )
    await menu_command(update, context)


async def update_menu_for_all_users(context: ContextTypes.DEFAULT_TYPE):
    """Принудительно обновляет меню у всех пользователей"""
    current_users, _ = load_data()

    for user_id in current_users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🔄 Меню бота было обновлено!",
                reply_markup=create_main_menu_keyboard(user_id in await is_admin(update.effective_user.id))
            )
        except Exception as e:
            logger.error(f"Не удалось обновить меню для {user_id}: {e}")


def create_main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Создает клавиатуру главного меню"""
    keyboard = [
        [COMMANDS['help']],
        [COMMANDS['foto'], COMMANDS['my_uploads']],
        [COMMANDS['delete_files'], COMMANDS['address']]
    ]

    if is_admin:
        keyboard.extend([
            [COMMANDS['random'], COMMANDS['message']],
            [COMMANDS['uploads_log']]
        ])

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает главное меню"""
    user = update.effective_user
    await update.message.reply_text(
        "📋 Главное меню:",
        reply_markup=create_main_menu_keyboard(user.id in await is_admin(update.effective_user.id))
    )


async def force_update_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно обновляет меню у всех пользователей (только для админов)"""
    if update.effective_user.id not in await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для админов!")
        return

    await update.message.reply_text("🔄 Начинаю обновление меню у всех пользователей...")
    await update_menu_for_all_users(context)
    await update.message.reply_text("✅ Меню успешно обновлено у всех пользователей!")


async def handle_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "❓ Помощь:\n\n"
        "• Отправьте фото/видео - я сохраню их и загружу в Фотоальбом\n"
        "• Форматы: JPG, PNG, HEIC, WEBP, MP4, MOV, AVI\n"
        "• Макс. размер видео: 20MB (2GB как документ)\n\n"
        "💬 Описание кнопок:\n\n"
        "📋 Меню бота /menu - открыть заново меню, если оно пропало.\n\n"
        f"📸 Фотоальбом /foto - получить ссылку на альбом.\n\n"
        "📊 Мои Загрузки /my_uploads - загруженные файлы\n\n"
        "🗑 Удалить мои файлы /delete_files - удаление загруженных файлов(выбираются по одному)\n\n"
        "📍 Как попасть на свадьбу /address - отправляет инструкцию и маршрут.\n\n"
        "Используйте кнопки внизу для быстрого доступа к командам.\n\n"
        "Если есть вопросы или ошибки писать в ЛС @godlike0101"
    )
    await update.message.reply_text(help_text)



async def handle_address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /address и кнопки '📍 Как попасть на свадьбу'"""
    # Текст сообщения
    caption_text = """
    \n🏢 Адрес: <b>Балтаси, улица Энергетиков, 27</b>\n
    При поездке из <b>Казани</b> используйте этот маршрут, так как Яндекс Карты могут повезти через плохую дорогу.
    При клике по ссылкам ниже, вас перебросить в приложение Яндекс карт, либо в веб-версию.
    <a href="https://yandex.ru/maps?rtext=55.796127,49.106414~56.347024,50.223617~56.338845,50.183142&rtt=auto">Маршрут для Яндекс Карт из Казани </a>
    <a href="https://yandex.ru/maps/-/CHc5RX3r">Точка, без маршрута</a>
    Нужно проехать через центр Балтаси, как на <b>первом скриншоте</b>.
    В конце маршрута не пропустите поворот налево, <b>второй скриншот</b>.
    """

    # Пути к фото
    photo_paths = [
        os.path.join("address_photo.jpg"),
        os.path.join("address_photo2.jpg"),
    ]

    # Фильтруем только существующие файлы
    existing_photos = [p for p in photo_paths if os.path.exists(p)]

    if not existing_photos:
        await update.message.reply_text("Фото временно недоступны 😢\n\n" + caption_text, parse_mode="HTML")
        return

    # Создаем медиагруппу
    media_group = []

    # Первое фото будет с подписью (caption)
    with open(existing_photos[0], 'rb') as photo_file:
        media_group.append(
            InputMediaPhoto(
                media=photo_file,
                caption=caption_text,
                parse_mode="HTML"
            )
        )

    # Остальные фото без подписи
    for photo_path in existing_photos[1:]:
        with open(photo_path, 'rb') as photo_file:
            media_group.append(
                InputMediaPhoto(media=photo_file)
            )

    # Отправляем медиагруппу
    await context.bot.send_media_group(
        chat_id=update.effective_chat.id,
        media=media_group
    )



async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик действий в админ-панели"""
    text = update.message.text
    user_id = update.effective_user.id

    if user_id not in await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для админов!")
        return

    if text == "Добавить админа":
        await update.message.reply_text(
            "Введите ID пользователя для добавления в админы:",
            reply_markup=ReplyKeyboardMarkup([["Отменить"]], resize_keyboard=True)
        )
        return "WAIT_ADMIN_ID"

    elif text == "Список админов":
        admins_list = "\n".join([f"👑 {users.get(admin_id, {}).get('name', 'Unknown')} (ID: {admin_id})"
                                 for admin_id in await is_admin(update.effective_user.id)])
        await update.message.reply_text(f"Список администраторов:\n\n{admins_list}")

    elif text == "Статистика":
        total_users = len(users)
        active_users = len([u for u in users.values() if
                            datetime.now() - datetime.strptime(u['last_seen'], "%Y-%m-%d %H:%M:%S") < timedelta(
                                days=7)])
        await update.message.reply_text(
            f"📊 Статистика:\n\n"
            f"Всего пользователей: {total_users}\n"
            f"Активных за неделю: {active_users}"
        )

    elif text == "Назад":
        await start(update, context)
        return ConversationHandler.END


async def handle_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик добавления нового админа"""
    try:
        new_admin_id = int(update.message.text)
        await is_admin(update.effective_user.id).add(new_admin_id)
        
        await update.message.reply_text(f"✅ Пользователь {new_admin_id} добавлен в админы!")
    except ValueError:
        await update.message.reply_text("❌ Некорректный ID. Введите число:")
        return "WAIT_ADMIN_ID"

    await admin_panel(update, context)
    return ConversationHandler.END

RANDOM_STATE = 1


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == COMMANDS['help'] or text == "/help":
        await handle_help_command(update, context)
        await update.message.reply_text(help_text)
    elif text == COMMANDS['address'] or text == "/address":
        await handle_address_command(update, context)
    elif text == COMMANDS['menu'] or text == "/menu":
        await menu_command(update, context)

    elif text == COMMANDS['foto']:
        await foto_command(update, context)

    elif text == COMMANDS['delete_files']:  # Новая команда
        return await delete_files_command(update, context)

    elif text == COMMANDS['random'] and user_id in await is_admin(update.effective_user.id):
        await update.message.reply_text(
            "Введите количество пользователей для выбора:",
            reply_markup=ReplyKeyboardMarkup([["Отменить"]], resize_keyboard=True)
        )
        return RANDOM_STATE

    elif text == COMMANDS['message'] and user_id in await is_admin(update.effective_user.id):
        await update.message.reply_text(
            "Введите текст для рассылки:",
            reply_markup=ReplyKeyboardMarkup([["Отменить"]], resize_keyboard=True)
        )
        return MESSAGE_STATE

    elif text == COMMANDS['uploads_log'] and user_id in await is_admin(update.effective_user.id):  # Новый обработчик
        await show_uploads_log(update, context)

    elif text == COMMANDS['my_uploads']:
        await my_uploads(update, context)

    else:
        await update.message.reply_text("Неизвестная команда. Используйте кнопки меню")


async def handle_message_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "Отменить":
        await start(update, context)
        return ConversationHandler.END

    # Сохраняем текст в context.user_data для использования в broadcast_message
    context.user_data['broadcast_text'] = text

    # Подтверждение перед рассылкой
    confirm_keyboard = ReplyKeyboardMarkup(
        [["✅ Подтвердить", "❌ Отменить"]],
        resize_keyboard=True
    )

    await update.message.reply_text(
        f"Подтвердите рассылку этого сообщения всем пользователям:\n\n{text}",
        reply_markup=confirm_keyboard
    )

    return MESSAGE_STATE + 1  # Переходим в состояние подтверждения


async def handle_confirm_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "✅ Подтвердить":
        # Имитируем команду /message с переданным текстом
        context.args = [context.user_data['broadcast_text']]
        await broadcast_message(update, context)
    elif text == "❌ Отменить":
        await update.message.reply_text("Рассылка отменена")

    await start(update, context)
    return ConversationHandler.END

async def handle_random_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "Отменить":
        await start(update, context)
        return ConversationHandler.END

    try:
        count = int(text)
        if count < 1:
            await update.message.reply_text("Число должно быть больше 0! Попробуйте снова:")
            return RANDOM_STATE

        # Вызываем random_user с переданным числом
        context.args = [str(count)]  # Имитируем аргументы команды
        await random_user(update, context)

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите целое число:")
        return RANDOM_STATE

    # Возвращаем основное меню
    await start(update, context)
    return ConversationHandler.END

async def random_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Проверяем, есть ли сообщение
        if not update.message:
            logger.error("Update.message is None!")
            return

        admin = update.effective_user
        if not admin:
            await update.message.reply_text("❌ Не удалось определить пользователя!")
            return

        if admin.id not in await is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только для админов!")
            return

        # Получаем количество пользователей для выбора
        try:
            count = int(context.args[0]) if context.args else 1
            if count < 1:
                await update.message.reply_text("❌ Число должно быть больше 0!")
                return
        except (IndexError, ValueError):
            await update.message.reply_text("❌ Используйте: /random [количество]")
            return

        # Загружаем свежие данные
        current_users, _ = load_data()

        # Фильтруем только активных обычных пользователей
        regular_users = {
            uid: data for uid, data in current_users.items()
            if uid not in await is_admin(update.effective_user.id)  # Не админ
               and str(uid) != str(admin.id)  # Не текущий пользователь
               and data.get('last_seen')  # Был активен
        }

        if not regular_users:
            await update.message.reply_text("❌ Нет подходящих пользователей для выбора!")
            return

        # Проверяем, достаточно ли пользователей
        if len(regular_users) < count:
            await update.message.reply_text(
                f"❌ Недостаточно пользователей (доступно: {len(regular_users)}, запрошено: {count})"
            )
            return

        # Преобразуем ID в строки для сравнения
        admin_ids = {str(uid) for uid in await is_admin(update.effective_user.id)}
        regular_users_list = [
            (uid, data) for uid, data in regular_users.items()
            if str(uid) not in admin_ids and str(uid) != str(admin.id)
        ]

        # Выбираем случайных пользователей без повторений
        selected = random.sample(regular_users_list, min(count, len(regular_users_list)))

        # Уведомляем победителей и формируем отчет
        report = ["🎲 Выбраны пользователи:"]
        success_count = 0

        for winner_id, winner_data in selected:
            try:
                # Дополнительная проверка
                if str(winner_id) in {str(uid) for uid in await is_admin(update.effective_user.id)}:
                    logger.error(f"Сбой фильтрации! Выбран админ: {winner_id}")
                    continue

                await context.bot.send_message(
                    chat_id=winner_id,
                    text=f"🎉 Поздравляю {winner_data['name']}, вы выбраны!\n\n"

                )
                report.append(
                    f"✅ {winner_data['name']} (ID: {winner_id}) "
                    f"@{winner_data.get('username', 'нет')} - уведомлен"
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Не удалось уведомить {winner_id}: {e}")
                report.append(
                    f"⚠️ {winner_data['name']} (ID: {winner_id}) "
                    f"- не удалось отправить уведомление"
                )

        # Отправляем отчет админу
        if update.message:
            await update.message.reply_text(
                "\n".join(report) +
                f"\n\nВсего выбрано: {len(selected)}\n"
                f"Успешно уведомлено: {success_count}"
            )

    except Exception as e:
        logger.error(f"Ошибка в /random: {e}", exc_info=True)
        if update and update.message:
            await update.message.reply_text("❌ Произошла ошибка при выборе победителей")


async def foto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /foto для отправки ссылки на фотоальбом"""
    await update.message.reply_text(
        text="📸 Вот ссылка на фотоальбом:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📷 Открыть фотоальбом", url=PHOTO_ALBUM_LINK)]
        ])
    )

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для админов!")
        return

    try:
        new_admin_id = int(context.args[0])
        await is_admin(update.effective_user.id).add(new_admin_id)
        
        await update.message.reply_text(f"✅ Пользователь {new_admin_id} добавлен в админы!")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Используйте: /add_admin [ID пользователя]")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        photo = await update.message.photo[-1].get_file()

        # Формируем имя файла с логином пользователя
        username_part = f"_{user.username}" if user.username else f"_{user.id}"
        file_name = f"photo_{update.message.id}{username_part}.jpg"

        file_path = os.path.join(MEDIA_FOLDER, file_name)
        await photo.download_to_drive(file_path)

        await update.message.reply_text(
            f"✅ Фото сохранено в папку '{MEDIA_FOLDER}'!\n"
            f"Имя файла: {file_name}"
        )

        # Логируем загрузку
        log_upload(
            user_id=user.id,
            user_name=user.full_name,
            username=user.username,
            file_name=file_name,
            file_type="photo"
        )

    except Exception as e:
        await update.message.reply_text("❌ Ошибка при сохранении фото")
        logger.error(f"Photo error: {e}")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        video = update.message.video

        if video.file_size > 1000 * 1024 * 1024:  # 20MB лимит
            await update.message.reply_text("❌ Видео слишком большое (максимум 20MB)")
            return

        # Формируем имя файла с логином пользователя
        username_part = f"_{user.username}" if user.username else f"_{user.id}"
        file_name = f"video_{update.message.id}{username_part}.mp4"

        file_path = os.path.join(MEDIA_FOLDER, file_name)
        await (await video.get_file()).download_to_drive(file_path)

        await update.message.reply_text(
            f"✅ Видео сохранено в папку '{MEDIA_FOLDER}'!\n"
            f"Имя файла: {file_name}"
        )

        # Логируем загрузку
        log_upload(
            user_id=user.id,
            user_name=user.full_name,
            username=user.username,
            file_name=file_name,
            file_type="video"
        )

    except Exception as e:
        await update.message.reply_text("❌ Ошибка при сохранении видео")
        logger.error(f"Video error: {e}")


async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Проверяем права админа
        if update.effective_user.id not in await is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только для админов!")
            return

        # Проверяем наличие текста сообщения
        if not context.args:
            await update.message.reply_text("❌ Используйте: /message [текст рассылки]")
            return

        message_text = " ".join(context.args)
        current_users, _ = load_data()

        # Фильтруем только обычных пользователей (не админов)
        regular_users = {
            uid: data for uid, data in current_users.items()
            if uid not in await is_admin(update.effective_user.id)
        }

        if not regular_users:
            await update.message.reply_text("❌ Нет пользователей для рассылки!")
            return

        success_count = 0
        failed_count = 0
        report = []

        # Отправляем сообщение каждому пользователю
        for user_id, user_data in regular_users.items():
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"{message_text}"
                )
                success_count += 1
                report.append(f"✅ {user_data['name']} (ID: {user_id}) - отправлено")
            except Exception as e:
                failed_count += 1
                report.append(f"⚠️ {user_data['name']} (ID: {user_id}) - ошибка: {str(e)}")
                logger.error(f"Не удалось отправить сообщение {user_id}: {e}")

        # Формируем итоговый отчет
        report_text = (
                f"📊 Итог рассылки:\n"
                f"Всего пользователей: {len(regular_users)}\n"
                f"Успешно: {success_count}\n"
                f"Не удалось: {failed_count}\n\n"
                f"Детали:\n" + "\n".join(report[:20])  # Ограничиваем количество строк в отчете
        )

        await update.message.reply_text(report_text)

    except Exception as e:
        logger.error(f"Ошибка в /message: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при рассылке сообщений")


async def notify_admins_about_upload(
        context: ContextTypes.DEFAULT_TYPE,
        user_name: str,
        username: str,
        file_name: str,
        file_type: str,
        file_size: int,
        update: Update
):
    """Отправляет уведомление с превью админам для всех типов файлов"""
    try:
        size_mb = file_size / (1024 * 1024)
        size_text = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{file_size / 1024:.1f} KB"

        message_text = (
            "📤 <b>Новый файл загружен</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_name}\n"
            f"🔹 <b>Логин:</b> @{username if username else 'нет'}\n"
            f"📁 <b>Файл:</b> {file_name}\n"
            f"🔧 <b>Тип:</b> {file_type}\n"
            f"📏 <b>Размер:</b> {size_text}\n"
            f"🕒 <b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        for admin_id in await is_admin(update.effective_user.id):
            try:
                # Определяем тип контента и отправляем соответствующее сообщение
                if update.message.photo:
                    # Обычное фото
                    photo_file = await update.message.photo[-1].get_file()
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=photo_file.file_id,
                        caption=message_text,
                        parse_mode="HTML"
                    )
                elif update.message.video:
                    # Видео
                    video_file = await update.message.video.get_file()
                    await context.bot.send_video(
                        chat_id=admin_id,
                        video=video_file.file_id,
                        caption=message_text,
                        parse_mode="HTML"
                    )
                elif update.message.document:
                    # Документ (проверяем тип)
                    doc = update.message.document
                    doc_file = await doc.get_file()

                    if doc.mime_type.startswith('image/'):
                        # Документ-изображение (отправляем как фото)
                        await context.bot.send_photo(
                            chat_id=admin_id,
                            photo=doc_file.file_id,
                            caption=message_text,
                            parse_mode="HTML"
                        )
                    elif doc.mime_type.startswith('video/'):
                        # Документ-видео (отправляем как видео)
                        await context.bot.send_video(
                            chat_id=admin_id,
                            video=doc_file.file_id,
                            caption=message_text,
                            parse_mode="HTML"
                        )
                    else:
                        # Другие типы документов (отправляем как документ)
                        await context.bot.send_document(
                            chat_id=admin_id,
                            document=doc_file.file_id,
                            caption=message_text,
                            parse_mode="HTML"
                        )
                else:
                    # Если тип не определен, отправляем просто текст
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=message_text,
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка в notify_admins_about_upload: {e}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        doc = update.message.document

        if doc.mime_type not in ALLOWED_MIME_TYPES:
            await update.message.reply_text("❌ Я принимаю только фото (JPG/PNG/HEIC) и видео (MP4/MOV)!")
            return

        if doc.mime_type.startswith("video/") and doc.file_size > 1000 * 1024 * 1024 * 1024:
            await update.message.reply_text("❌ Видео слишком большое (максимум 2GB)")
            return

        # Определяем тип и расширение файла
        if doc.mime_type.startswith("image/"):
            if doc.mime_type in ("image/heic", "image/heif"):
                file_ext = "heic"
            else:
                file_ext = doc.file_name.split(".")[-1].lower() if doc.file_name else "jpg"
            file_type = "фото"
        else:
            file_ext = doc.file_name.split(".")[-1].lower() if doc.file_name else "mp4"
            file_type = "видео"

        # Формируем новое имя файла с логином пользователя
        username_part = f"_{user.username}" if user.username else f"_{user.id}"
        original_name = doc.file_name or f"{file_type}_doc_{update.message.id}"
        base_name = os.path.splitext(original_name)[0]
        file_name = f"{base_name}{username_part}.{file_ext}"

        file_path = os.path.join(MEDIA_FOLDER, file_name)
        await (await doc.get_file()).download_to_drive(file_path)

        await update.message.reply_text(
            f"✅ {file_type.capitalize()} сохранено в папку '{MEDIA_FOLDER}'!\n"
            f"Имя файла: {file_name}"
        )

        # Логируем загрузку
        log_upload(
            user_id=user.id,
            user_name=user.full_name,
            username=user.username,
            file_name=file_name,
            file_type="document"
        )

        # Уведомляем админов
        await notify_admins_about_upload(
            context=context,
            user_name=user.full_name,
            username=user.username,
            file_name=file_name,
            file_type=file_type,
            file_size=doc.file_size,
            update=update
        )

    except Exception as e:
        await update.message.reply_text("❌ Ошибка при сохранении файла")
        logger.error(f"Document error: {e}")


def get_user_files(user_id: int, username: str = None):
    """Возвращает список файлов пользователя"""
    try:
        if not os.path.exists(MEDIA_FOLDER):
            return []

        user_files = []
        for filename in os.listdir(MEDIA_FOLDER):
            # Проверяем принадлежность файла пользователю
            if f"_{user_id}." in filename or (username and f"_{username}." in filename):
                file_path = os.path.join(MEDIA_FOLDER, filename)
                user_files.append({
                    'name': filename,
                    'path': file_path,
                    'time': os.path.getmtime(file_path)
                })

        # Сортируем по дате (новые сначала)
        return sorted(user_files, key=lambda x: x['time'], reverse=True)
    except Exception as e:
        logger.error(f"Ошибка при получении файлов пользователя: {e}")
        return []


async def handle_page_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик переключения страниц"""
    query = update.callback_query
    await query.answer()

    current_page = context.user_data.get('current_page', 0)

    if query.data == "prev_page":
        new_page = current_page - 1
    else:
        new_page = current_page + 1

    return await send_files_page(update, context, new_page)


async def send_files_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Отправляет новую страницу с мгновенным удалением предыдущих"""
    # Удаляем ВСЕ предыдущие сообщения (превью и кнопки) одним запросом
    await clean_messages(context, update.effective_chat.id)

    user_files = context.user_data.get('user_files', [])
    if not user_files:
        msg = await update.effective_message.reply_text("У вас нет загруженных файлов.")
        context.user_data['last_message_id'] = msg.message_id
        return ConversationHandler.END

    total_pages = (len(user_files) + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    context.user_data['current_page'] = page
    start_idx = page * PAGE_SIZE
    page_files = user_files[start_idx:start_idx + PAGE_SIZE]

    # 1. Отправляем все превью как одну медиагруппу (до 10 файлов)
    media_messages = []
    try:
        media_group = []
        for i, file_info in enumerate(page_files, 1):
            file_path = file_info['path']
            filename = os.path.basename(file_info['name'])

            with open(file_path, 'rb') as f:
                if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    media_group.append(InputMediaPhoto(
                        media=f,
                        caption=f"Файл {start_idx + i}: {filename}"
                    ))
                else:
                    media_group.append(InputMediaDocument(
                        media=f,
                        caption=f"Файл {start_idx + i}: {filename}"
                    ))

        # Разбиваем на группы по 10 файлов (ограничение Telegram)
        for chunk in [media_group[i:i + 10] for i in range(0, len(media_group), 10)]:
            messages = await context.bot.send_media_group(
                chat_id=update.effective_chat.id,
                media=chunk
            )
            media_messages.extend(messages)

    except Exception as e:
        logger.error(f"Ошибка отправки превью: {e}")

    # 2. Отправляем сообщение с кнопками
    try:
        keyboard = []
        for file_info in page_files:
            filename = os.path.basename(file_info['name'])
            keyboard.append([InlineKeyboardButton(
                f"🗑 {filename[:20]}{'...' if len(filename) > 20 else ''}",
                callback_data=f"delete_{file_info['name']}"
            )])

        # Навигация
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="prev_page"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data="next_page"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton("❌ Отменить", callback_data="cancel_delete")])

        control_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Страница {page + 1}/{total_pages}. Выберите файл для удаления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Сохраняем ID всех сообщений для последующего удаления
        context.user_data['media_message_ids'] = [msg.message_id for msg in media_messages]
        context.user_data['last_message_id'] = control_message.message_id

    except Exception as e:
        logger.error(f"Ошибка отправки клавиатуры: {e}")
        await clean_messages(context, update.effective_chat.id)
        return ConversationHandler.END

    return DELETE_STATE


async def delete_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды удаления файлов"""
    user = update.effective_user
    user_files = get_user_files(user.id, user.username)  # Передаем и ID и username

    if not user_files:
        await update.message.reply_text("У вас нет загруженных файлов.")
        return ConversationHandler.END

    context.user_data['user_files'] = user_files
    context.user_data['current_page'] = 0

    return await send_files_page(update, context)


async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик удаления конкретного файла"""
    query = update.callback_query
    await query.answer()

    filename = query.data.replace("delete_", "", 1)
    filepath = os.path.join(MEDIA_FOLDER, filename)

    try:
        # Удаляем файл
        if os.path.exists(filepath):
            os.remove(filepath)

        # Обновляем список файлов
        context.user_data['user_files'] = [f for f in context.user_data['user_files'] if f['name'] != filename]

        # Проверяем, остались ли файлы
        if not context.user_data['user_files']:
            await clean_messages(context, query.message.chat.id)
            await query.message.reply_text("✅ Файлы удалёны! У вас больше нет файлов.")
            return ConversationHandler.END

        # Обновляем текущую страницу
        current_page = context.user_data.get('current_page', 0)
        return await send_files_page(update, context, current_page)

    except Exception as e:
        logger.error(f"Ошибка удаления файла: {e}")
        await query.message.reply_text("❌ Ошибка при удалении файла!")
        return DELETE_STATE

async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все callback-запросы"""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("delete_"):
        return await delete_file(update, context)
    elif query.data in ["prev_page", "next_page"]:
        return await handle_page_navigation(update, context)
    elif query.data == "cancel_delete":
        await clean_messages(context, query.message.chat_id)
        await query.message.reply_text("Удаление отменено.")
        return ConversationHandler.END

    return DELETE_STATE


async def clean_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Удаляет все сообщения (включая превью) максимально эффективно"""
    try:
        # Получаем все ID сообщений для удаления
        message_ids = []
        if 'media_message_ids' in context.user_data:
            message_ids.extend(context.user_data['media_message_ids'])
        if 'last_message_id' in context.user_data:
            message_ids.append(context.user_data['last_message_id'])

        if not message_ids:
            return

        logger.debug(f"Начало удаления {len(message_ids)} сообщений...")

        # Создаем и запускаем задачи удаления
        tasks = []
        for msg_id in message_ids:
            task = asyncio.create_task(
                safe_delete_message(context.bot, chat_id, msg_id),
                name=f"delete_msg_{msg_id}"
            )
            tasks.append(task)

        # Ожидаем завершения с таймаутом
        done, pending = await asyncio.wait(tasks, timeout=3.0)

        # Логируем результаты
        logger.debug(f"Удалено {len(done)} сообщений, {len(pending)} не завершены")

        # Очищаем сохраненные ID независимо от результата
        context.user_data.pop('media_message_ids', None)
        context.user_data.pop('last_message_id', None)

    except Exception as e:
        logger.error(f"Критическая ошибка в clean_messages: {e}")


async def safe_delete_message(bot, chat_id, message_id):
    """Безопасное удаление одного сообщения с обработкой ошибок"""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except telegram.error.BadRequest as e:
        if "message to delete not found" not in str(e):
            logger.warning(f"Не удалось удалить сообщение {message_id}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Ошибка при удалении сообщения {message_id}: {e}")
        return False


async def cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик отмены удаления"""
    query = update.callback_query
    await query.answer()

    await clean_messages(context, query.message.chat.id)
    await query.message.reply_text("🗑 Удаление отменено.")
    return ConversationHandler.END


def create_media_group(files: list, start_idx: int) -> list:
    """Создает медиа-группу для отправки"""
    media_group = []
    for i, file_info in enumerate(files, 1):
        file_path = file_info['path']
        filename = os.path.basename(file_info['name'])

        with open(file_path, 'rb') as f:
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                media_group.append(InputMediaPhoto(
                    media=f,
                    caption=f"Файл {start_idx + i}: {filename}"
                ))
            elif filename.lower().endswith(('.mp4', '.mov', '.avi')):
                media_group.append(InputMediaVideo(
                    media=f,
                    caption=f"Файл {start_idx + i}: {filename}"
                ))
            else:
                media_group.append(InputMediaDocument(
                    media=f,
                    caption=f"Файл {start_idx + i}: {filename}"
                ))
    return media_group


def create_keyboard(files: list, current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для управления файлами"""
    buttons = []
    for file_info in files:
        filename = os.path.basename(file_info['name'])
        buttons.append([
            InlineKeyboardButton(
                f"🗑 {filename[:15]}{'...' if len(filename) > 15 else ''}",
                callback_data=f"delete_{file_info['name']}"
            )
        ])

    # Кнопки навигации
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="prev_page"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data="next_page"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("❌ Отменить", callback_data="cancel_delete")])

    return InlineKeyboardMarkup(buttons)


async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет выбранный файл"""
    query = update.callback_query
    filename = query.data[7:]

    try:
        # Удаляем файл
        filepath = os.path.join(MEDIA_FOLDER, filename)
        if os.path.exists(filepath):
            os.remove(filepath)

        # Обновляем список файлов
        context.user_data['user_files'] = [f for f in context.user_data['user_files'] if f['name'] != filename]

        # Если файлов не осталось
        if not context.user_data['user_files']:
            await clean_messages(context, query.message.chat_id)
            await query.message.reply_text("✅ Файл удален! У вас больше нет файлов.")
            return ConversationHandler.END

        # Показываем обновленную страницу
        current_page = context.user_data.get('current_page', 0)
        return await send_files_page(update, context, current_page)

    except Exception as e:
        logger.error(f"Ошибка удаления файла: {e}")
        await query.message.reply_text("❌ Ошибка при удалении файла!")
        return DELETE_STATE

from db import init_db
import asyncio

async def main():
    asyncio.run(init_db())
    # Правильная конфигурация для локального API
    application = (
        Application.builder()
        .token(TOKEN)
#        .base_url(f"{LOCAL_API_URL}/bot")
        .connect_timeout(30)  # 30 секунд на подключение
        .read_timeout(300)  # 5 минут на загрузку
        .write_timeout(300)  # 5 минут на отправку
        .build()
    )
    # Обработчик удаления файлов
    delete_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.TEXT & filters.Regex(f"^{COMMANDS['delete_files']}$"),
                delete_files_command
            )
        ],
        states={
            DELETE_STATE: [
                CallbackQueryHandler(handle_delete, pattern="^delete_"),
                CallbackQueryHandler(handle_page_navigation, pattern="^(prev_page|next_page)$"),
                CallbackQueryHandler(cancel_delete, pattern="^cancel_delete$")
            ]
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^(Отменить|Назад)$"), start)
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
        conversation_timeout=300  # 5 минут таймаут на неактивность
    )

    application.add_handler(delete_conv_handler)
    # Обработчики остаются без изменений
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_media))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        ],
        states={
            RANDOM_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_random_state)],
            MESSAGE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_state)],
            "WAIT_ADMIN_ID": [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_admin)],
            MESSAGE_STATE + 1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirm_state)]
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^Отменить$"), start),
            MessageHandler(filters.Regex("^Назад$"), start)
        ]
    )

    application.add_handler(conv_handler)

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("random", random_user))
    application.add_handler(CommandHandler("add_admin", add_admin))
    application.add_handler(CommandHandler("message", broadcast_message))
    application.add_handler(CommandHandler("foto", foto_command))
    application.add_handler(CommandHandler("uploads_log", show_uploads_log))
    application.add_handler(CommandHandler("my_uploads", my_uploads))
    application.add_handler(CommandHandler("help", handle_help_command))
    application.add_handler(CommandHandler("delete_files", delete_files_command))
    application.add_handler(CommandHandler("address", handle_address_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("force_update_menu", force_update_menu))
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))


    logger.info(f"Бот запущен")
    await application.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
