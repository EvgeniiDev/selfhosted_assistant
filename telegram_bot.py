from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from chat_application_service import ChatApplicationService, ChatResponse
from voice_service import VoiceService
from voice_input_service import VoiceInputService
from logger import calendar_logger


class TelegramBot:
    TELEGRAM_MAX_MESSAGE = 3900

    SUPPORTED_AUDIO_EXTENSIONS = {
        "mp3", "wav", "ogg", "oga", "opus", "m4a", "mp4", "aac", "flac", "webm"
    }

    def __init__(self, token: str):
        self.token = token
        self.chat_service = ChatApplicationService()
        self.research_service = self.chat_service.research_service
        self.voice_service = VoiceService(device="cpu")  # Используем CPU для инференса
        self.voice_input_service = VoiceInputService(self.voice_service, self.chat_service)
        self.application = Application.builder().token(token).build()
        
        # Настройка разрешенных пользователей
        allowed_users_str = os.getenv('TELEGRAM_ALLOWED_USERS', '').strip()
        if allowed_users_str:
            # Парсим список пользователей (может быть username или user_id)
            self.allowed_users = set()
            for user in allowed_users_str.split(','):
                user = user.strip()
                if user:
                    # Если это число, добавляем как user_id, иначе как username
                    if user.isdigit():
                        self.allowed_users.add(int(user))
                    else:
                        # Убираем @ если есть
                        username = user.lstrip('@').lower()
                        self.allowed_users.add(username)
        else:
            self.allowed_users = None  # None означает разрешено всем
            
        self._setup_handlers()

    def _safe_url_encode(self, url: str) -> str:
        """Безопасное кодирование URL для Telegram"""
        if not url:
            return ""
        
        # Для Telegram лучше использовать HTML формат ссылок
        # или просто возвращать URL как есть для HTML parse_mode
        return url

    def _is_user_allowed(self, update: Update) -> bool:
        """Проверка, разрешен ли пользователь для использования бота"""
        if self.allowed_users is None:
            return True  # Если список не настроен, разрешаем всем
            
        user = update.effective_user
        if not user:
            return False
            
        # Проверяем по user_id
        if user.id in self.allowed_users:
            return True
            
        # Проверяем по username
        if user.username and user.username.lower() in self.allowed_users:
            return True
            
        return False

    async def _send_access_denied_message(self, update: Update):
        """Отправка сообщения о запрете доступа"""
        await update.message.reply_text(
            "❌ У вас нет доступа к этому боту.\n"
            "Обратитесь к администратору для получения разрешения."
        )

    def _setup_handlers(self):
        """Настройка обработчиков команд и сообщений"""
        self.application.add_handler(
            CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("research_help", self.research_help_command))
        self.application.add_handler(CommandHandler("research_reset", self.research_reset_command))
        self.application.add_handler(CommandHandler("research_sources", self.research_sources_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(MessageHandler(filters.VOICE, self.handle_voice_message))  # Обработчик голосовых сообщений
        self.application.add_handler(MessageHandler(filters.AUDIO | filters.Document.ALL, self.handle_audio_file_message))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        # Проверка разрешенных пользователей
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return
            
        welcome_message = (
            "Привет! Я ассистент для создания событий в Google Calendar и сохранения заметок.\n\n"
            "Вы можете:\n"
            "📝 Написать текстовое сообщение\n"
            "🎤 Записать голосовое сообщение\n"
            "🎵 Отправить аудиофайл (mp3/wav)\n\n"
            "Примеры запросов:\n"
            "📅 **Календарные события:**\n"
            "• 'Встреча с командой завтра в 14:00 на час'\n"
            "• 'Обед каждый день в 13:00 на 30 минут'\n"
            "• 'Планерка в понедельник в 10:00'\n\n"
            "📝 **Заметки:**\n"
            "• 'Запомни: нужно купить молоко и хлеб'\n"
            "• 'Заметка: идея для проекта'\n"
            "• 'Нужно позвонить маме'\n\n"
            "Я автоматически определю, что вы хотите - создать событие в календаре или сохранить заметку.\n"
            "Используйте /help для получения дополнительной информации.\n\n"
            "🔎 Research mode:\n"
            "• 'Исследуй тему квантовых батарей'\n"
            "• 'Подробнее про пункт 2' (follow-up)\n"
            "• /research_help, /research_sources, /research_reset"
        )
        await update.message.reply_text(welcome_message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        # Проверка разрешенных пользователей
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return
            
        help_message = (
            "Как использовать бота:\n\n"
            "📅 **Для календарных событий:**\n"
            "1️⃣ Отправьте описание события:\n"
            "   📝 Текстовое сообщение, 🎤 голосовое сообщение или 🎵 аудиофайл (mp3/wav)\n"
            "2️⃣ Проверьте детали события в предварительном просмотре\n"
            "3️⃣ Нажмите \"✅ Подтвердить\" для создания или \"❌ Отменить\"\n"
            "4️⃣ Если что-то не так, нажмите \"✏️ Редактировать\"\n\n"
            "Вы можете указать:\n"
            "• Название события (обязательно)\n"
            "• Описание\n"
            "• Время начала\n"
            "• Время окончания или длительность\n"
            "• Повторяемость (каждый день, каждую неделю и т.д.)\n\n"
            "Примеры календарных событий:\n"
            "• 'Встреча с клиентом завтра в 15:00 длительностью 2 часа'\n"
            "• 'Спортзал каждый понедельник в 19:00'\n"
            "• 'Обед сегодня в 13:00-14:00'\n\n"
            "📝 **Для заметок:**\n"
            "Просто напишите то, что хотите запомнить:\n"
            "• 'Нужно купить молоко и хлеб'\n"
            "• 'Идея: создать чат-бот для заказов'\n"
            "• 'Запомни номер телефона: +7-123-456-78-90'\n\n"
            "🤖 **Автоматическое определение типа:**\n"
            "Бот сам определит, хотите ли вы создать событие в календаре (с указанием времени) или просто сохранить заметку.\n\n"
            "🎤 Голосовые сообщения и 🎵 аудиофайлы (mp3/wav) автоматически распознаются и обрабатываются как текст.\n\n"
            "🔎 **Research mode:**\n"
            "• Напишите: 'Исследуй ...', 'Проведи исследование ...', 'deep dive ...'\n"
            "• Follow-up запросы ('подробнее', 'раскрой пункт N') используют сохраненный контекст\n"
            "• Команды: /research_help, /research_sources, /research_reset"
        )
        await update.message.reply_text(help_message)

    async def research_help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return

        msg = (
            "🔎 Research mode\n\n"
            "Как использовать:\n"
            "1) Новый ресерч: 'Исследуй тему ИИ-агентов в медицине'\n"
            "2) Follow-up: 'Подробнее про пункт 2'\n"
            "3) Источники: /research_sources\n"
            "4) Сброс контекста: /research_reset\n\n"
            "Формат ответа: краткий итог, статусы фактов [CONFIRMED]/[UNCERTAIN]/[NOT_FOUND], ссылки, что еще проверить."
        )
        await update.message.reply_text(msg)

    async def research_reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return

        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        cleared = self.research_service.reset_chat(chat_id)
        if cleared:
            await update.message.reply_text("🧹 Research контекст для этого чата сброшен.")
        else:
            await update.message.reply_text("ℹ️ Для этого чата пока нет активного research-контекста.")

    async def research_sources_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return

        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        urls = self.research_service.list_sources(chat_id)
        if not urls:
            await update.message.reply_text("ℹ️ Источники не найдены. Сначала запустите research-запрос.")
            return

        lines = ["📚 Сохраненные источники:"]
        for idx, url in enumerate(urls, start=1):
            lines.append(f"{idx}. {url}")
        await self._send_long_message(update.message, "\n".join(lines))

    async def handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик голосовых сообщений"""
        # Проверка разрешенных пользователей
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return
            
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        user_id = str(update.effective_user.id) if update.effective_user else None
        username = update.effective_user.username if update.effective_user else None
        message_id = update.message.message_id if update.message else None

        # Показываем, что бот обрабатывает голосовое сообщение
        processing_message = await update.message.reply_text("🎤 Обрабатываю голосовое сообщение...")

        try:
            # Проверяем, загружена ли модель
            if not self.voice_input_service.is_model_loaded():
                await processing_message.edit_text("❌ Модель распознавания речи не загружена")
                return

            # Получаем голосовое сообщение
            voice = update.message.voice
            voice_file = await context.bot.get_file(voice.file_id)

            # Обновляем статус
            await processing_message.edit_text("🎤 Распознаю речь...")

            result = await self.voice_input_service.process_voice_message(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                message_id=message_id,
                voice_file=voice_file,
            )
            await processing_message.edit_text(
                f"🎤 Распознанный текст: *{result.transcription}*\n\nОбрабатываю запрос...",
                parse_mode='Markdown'
            )
            await self._render_chat_response(update, result.chat_response, processing_message)

        except Exception as e:
            calendar_logger.log_error(e, "telegram_bot.handle_voice_message")
            error_message = f"❌ Произошла ошибка при обработке голосового сообщения: {str(e)}"
            await processing_message.edit_text(error_message)

    def _detect_audio_extension(self, filename: Optional[str], mime_type: Optional[str]) -> Optional[str]:
        if filename and "." in filename:
            ext = filename.rsplit(".", 1)[-1].lower()
            if ext in self.SUPPORTED_AUDIO_EXTENSIONS:
                return ext

        if mime_type:
            normalized = mime_type.lower().split(";", 1)[0].strip()
            if normalized in {"audio/mpeg", "audio/mp3"}:
                return "mp3"
            if normalized in {"audio/wav", "audio/x-wav", "audio/wave"}:
                return "wav"
            if normalized in {"audio/ogg", "application/ogg"}:
                return "ogg"
            if normalized in {"audio/opus", "audio/opus+ogg"}:
                return "opus"
            if normalized in {"audio/mp4", "audio/x-m4a", "audio/m4a"}:
                return "m4a"
            if normalized in {"audio/aac", "audio/x-aac"}:
                return "aac"
            if normalized in {"audio/flac", "audio/x-flac"}:
                return "flac"
            if normalized in {"audio/webm"}:
                return "webm"

        return None

    async def handle_audio_file_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик аудиофайлов"""
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return

        message = update.message
        if not message:
            return

        user_id = str(update.effective_user.id) if update.effective_user else None
        username = update.effective_user.username if update.effective_user else None
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        message_id = update.message.message_id if update.message else None

        audio_obj = None
        filename = None
        mime_type = None
        source_label = "AUDIO"

        if message.audio:
            audio_obj = message.audio
            filename = message.audio.file_name
            mime_type = message.audio.mime_type
        elif message.document:
            filename = message.document.file_name
            mime_type = message.document.mime_type
            ext = self._detect_audio_extension(filename, mime_type)
            if ext:
                audio_obj = message.document
                source_label = "AUDIO_FILE"

        if audio_obj is None:
            return

        detected_ext = self._detect_audio_extension(filename, mime_type)
        if detected_ext is None:
            supported = ", ".join(sorted(self.SUPPORTED_AUDIO_EXTENSIONS))
            await message.reply_text(f"❌ Неподдерживаемый аудиоформат. Поддерживаются: {supported}.")
            return

        processing_message = await message.reply_text("🎵 Обрабатываю аудиофайл...")

        try:
            if not self.voice_input_service.is_model_loaded():
                await processing_message.edit_text("❌ Модель распознавания речи не загружена")
                return

            tg_file = await context.bot.get_file(audio_obj.file_id)
            await processing_message.edit_text("🎵 Распознаю речь...")

            result = await self.voice_input_service.process_audio_file(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                message_id=message_id,
                audio_file=tg_file,
                source_extension=detected_ext,
                source_label=source_label,
            )
            await processing_message.edit_text(
                f"🎵 Распознанный текст: *{result.transcription}*\n\nОбрабатываю запрос...",
                parse_mode='Markdown'
            )
            await self._render_chat_response(update, result.chat_response, processing_message)

        except Exception as e:
            calendar_logger.log_error(e, "telegram_bot.handle_audio_file_message")
            await processing_message.edit_text(f"❌ Произошла ошибка при обработке аудиофайла: {str(e)}")

    async def _process_text_request(self, update: Update, user_message: str, processing_message=None):
        """Общий метод для обработки текстовых запросов"""
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        user_id = str(update.effective_user.id) if update.effective_user else None
        message_id = update.message.message_id if update.message else None

        try:
            response = self.chat_service.process_text(chat_id, user_id, message_id, user_message)
            await self._render_chat_response(update, response, processing_message)

        except Exception as e:
            calendar_logger.log_error(e, "telegram_bot._process_text_request")
            error_message = f"❌ Произошла ошибка: {str(e)}"
            if processing_message:
                await processing_message.edit_text(error_message)
            else:
                await update.message.reply_text(error_message)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        # Проверка разрешенных пользователей
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return
            
        user_message = update.message.text
        user_id = str(update.effective_user.id) if update.effective_user else None
        username = update.effective_user.username if update.effective_user else None

        # Логируем запрос пользователя
        calendar_logger.log_user_request(user_id, username, user_message)

        # Показываем, что бот обрабатывает запрос
        processing_message = await update.message.reply_text("Обрабатываю ваш запрос...")

        # Используем общий метод для обработки
        await self._process_text_request(update, user_message, processing_message)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на inline кнопки"""
        query = update.callback_query
        await query.answer()

        data = query.data
        
        if data.startswith("confirm_"):
            event_id = data.replace("confirm_", "")
            await self._confirm_event(query, event_id)
        elif data.startswith("cancel_"):
            event_id = data.replace("cancel_", "")
            await self._cancel_event(query, event_id)
        elif data.startswith("edit_"):
            event_id = data.replace("edit_", "")
            await self._edit_event(query, event_id)

    async def _confirm_event(self, query, event_id: str):
        """Подтверждение создания события"""
        response = self.chat_service.confirm_pending(event_id)
        await self._edit_callback_message(query, response)

    async def _cancel_event(self, query, event_id: str):
        """Отмена создания события"""
        response = self.chat_service.cancel_pending(event_id)
        await self._edit_callback_message(query, response)

    async def _edit_event(self, query, event_id: str):
        """Редактирование события"""
        response = self.chat_service.edit_pending(event_id)
        await self._edit_callback_message(query, response)

    async def _render_chat_response(self, update: Update, response: ChatResponse, processing_message=None):
        reply_markup = self._build_confirmation_markup(response.pending_id) if response.needs_confirmation else None
        if processing_message:
            await processing_message.edit_text(
                response.text,
                parse_mode=response.parse_mode,
                disable_web_page_preview=response.disable_web_page_preview,
                reply_markup=reply_markup,
            )
            return

        await update.message.reply_text(
            response.text,
            parse_mode=response.parse_mode,
            disable_web_page_preview=response.disable_web_page_preview,
            reply_markup=reply_markup,
        )

    async def _edit_callback_message(self, query, response: ChatResponse):
        try:
            await query.edit_message_text(
                response.text,
                parse_mode=response.parse_mode,
                disable_web_page_preview=response.disable_web_page_preview,
            )
        except Exception:
            await query.edit_message_text(response.text)

    def _build_confirmation_markup(self, pending_id: str) -> InlineKeyboardMarkup | None:
        if not pending_id:
            return None

        keyboard = [
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{pending_id}"),
                InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{pending_id}"),
            ],
            [
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{pending_id}"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def _send_long_message(self, message, text: str, parse_mode: Optional[str] = None):
        if not text:
            return

        chunks = self._split_text_chunks(text, self.TELEGRAM_MAX_MESSAGE)
        for chunk in chunks:
            await message.reply_text(chunk, parse_mode=parse_mode, disable_web_page_preview=True)

    def _split_text_chunks(self, text: str, chunk_size: int) -> list[str]:
        if len(text) <= chunk_size:
            return [text]

        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= chunk_size:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n", 0, chunk_size)
            if split_at < 200:
                split_at = chunk_size
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip("\n")

        return chunks

    def run(self):
        """Запуск бота"""
        print("Запуск Telegram бота...")
        
        # Информация о разрешенных пользователях
        if self.allowed_users is None:
            print("👥 Доступ разрешен всем пользователям")
        else:
            users_count = len(self.allowed_users)
            print(f"🔒 Доступ ограничен для {users_count} пользователь(ей)")
        
        # Проверяем статус модели распознавания речи
        if self.voice_service.is_model_loaded():
            print("✅ Модель распознавания речи загружена успешно")
        else:
            print("⚠️  Модель распознавания речи не загружена. Голосовые сообщения не будут обрабатываться.")
        
        self.application.run_polling()

