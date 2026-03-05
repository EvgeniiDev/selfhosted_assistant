from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from assistant_service import AssistantService
from voice_service import VoiceService
from logger import calendar_logger
from llm_core import LLMRequest
from research_context_store import ResearchContextStore


class TelegramBot:
    TELEGRAM_MAX_MESSAGE = 3900

    SUPPORTED_AUDIO_EXTENSIONS = {
        "mp3", "wav", "ogg", "oga", "opus", "m4a", "mp4", "aac", "flac", "webm"
    }

    def __init__(self, token: str):
        self.token = token
        self.assistant_service = AssistantService()
        self.voice_service = VoiceService(device="cpu")  # Используем CPU для инференса
        self.application = Application.builder().token(token).build()
        # Хранилище для ожидающих подтверждения событий
        self.pending_events = {}
        self.research_store = ResearchContextStore()
        
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
        cleared = self.research_store.reset_chat(chat_id)
        if cleared:
            await update.message.reply_text("🧹 Research контекст для этого чата сброшен.")
        else:
            await update.message.reply_text("ℹ️ Для этого чата пока нет активного research-контекста.")

    async def research_sources_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_user_allowed(update):
            await self._send_access_denied_message(update)
            return

        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        urls = self.research_store.list_sources(chat_id)
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
            
        user_id = str(update.effective_user.id) if update.effective_user else None
        username = update.effective_user.username if update.effective_user else None

        # Показываем, что бот обрабатывает голосовое сообщение
        processing_message = await update.message.reply_text("🎤 Обрабатываю голосовое сообщение...")

        try:
            # Проверяем, загружена ли модель
            if not self.voice_service.is_model_loaded():
                await processing_message.edit_text("❌ Модель распознавания речи не загружена")
                return

            # Получаем голосовое сообщение
            voice = update.message.voice
            voice_file = await context.bot.get_file(voice.file_id)

            # Обновляем статус
            await processing_message.edit_text("🎤 Распознаю речь...")

            # Транскрибируем голосовое сообщение
            transcription = await self.voice_service.transcribe_voice_message(voice_file)

            if not transcription:
                await processing_message.edit_text("❌ Не удалось распознать речь. Попробуйте записать сообщение заново.")
                return

            # Логируем запрос пользователя
            calendar_logger.log_user_request(user_id, username, f"[VOICE] {transcription}")

            # Показываем распознанный текст пользователю
            await processing_message.edit_text(f"🎤 Распознанный текст: *{transcription}*\n\nОбрабатываю запрос...", parse_mode='Markdown')

            # Обрабатываем транскрибированный текст как обычное текстовое сообщение
            await self._process_text_request(update, transcription, processing_message)

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
            if not self.voice_service.is_model_loaded():
                await processing_message.edit_text("❌ Модель распознавания речи не загружена")
                return

            tg_file = await context.bot.get_file(audio_obj.file_id)
            await processing_message.edit_text("🎵 Распознаю речь...")

            transcription = await self.voice_service.transcribe_audio_file(tg_file, source_extension=detected_ext)

            if not transcription:
                await processing_message.edit_text("❌ Не удалось распознать речь из аудиофайла. Попробуйте другой файл.")
                return

            calendar_logger.log_user_request(user_id, username, f"[{source_label}] {transcription}")

            await processing_message.edit_text(
                f"🎵 Распознанный текст: *{transcription}*\n\nОбрабатываю запрос...",
                parse_mode='Markdown'
            )

            await self._process_text_request(update, transcription, processing_message)

        except Exception as e:
            calendar_logger.log_error(e, "telegram_bot.handle_audio_file_message")
            await processing_message.edit_text(f"❌ Произошла ошибка при обработке аудиофайла: {str(e)}")

    async def _process_text_request(self, update: Update, user_message: str, processing_message=None):
        """Общий метод для обработки текстовых запросов"""
        user_id = str(update.effective_user.id) if update.effective_user else None
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""

        try:
            if self._should_force_research_new(chat_id, user_message):
                forced_result = {
                    "success": True,
                    "action": "research",
                    "original_query": user_message,
                    "mode": "new",
                }
                await self._handle_research_action(update, user_message, forced_result, processing_message)
                return

            if self._should_force_research_followup(chat_id, user_message):
                forced_result = {
                    "success": True,
                    "action": "research",
                    "original_query": user_message,
                    "mode": "followup",
                }
                await self._handle_research_action(update, user_message, forced_result, processing_message)
                return

            # Обрабатываем запрос через ассистент сервис
            result = self.assistant_service.process_user_request(user_message)

            if result.get('success') and result.get('action') == 'confirm':
                # Событие готово к подтверждению
                event = result['event']
                message = result['message']
                
                # Сохраняем событие для подтверждения
                event_id = f"{user_id}_{update.message.message_id}"
                self.pending_events[event_id] = {"type": "event", "payload": event}
                
                # Создаем клавиатуру с кнопками
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{event_id}"),
                        InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{event_id}")
                    ],
                    [
                        InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{event_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if processing_message:
                    await processing_message.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                else:
                    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                
            elif result.get('success') and result.get('action') == 'note':
                if self._should_force_research_followup(chat_id, user_message):
                    forced_result = {
                        "success": True,
                        "action": "research",
                        "original_query": user_message,
                        "mode": "followup",
                    }
                    await self._handle_research_action(update, user_message, forced_result, processing_message)
                    return

                # Заметка - отправляем её пользователю сразу
                note_message = result['message']
                
                if processing_message:
                    await processing_message.edit_text(note_message, parse_mode='Markdown')
                else:
                    await update.message.reply_text(note_message, parse_mode='Markdown')

            elif result.get('success') and result.get('action') == 'research':
                await self._handle_research_action(update, user_message, result, processing_message)
                
            elif result.get('success'):
                # Generic success (e.g., task confirm)
                # Если это подтверждение задачи — сохраним payload как задачу
                if result.get('action') == 'confirm_task':
                    task = result['task']
                    event_id = f"{user_id}_{update.message.message_id}"
                    self.pending_events[event_id] = {"type": "task", "payload": task}
                    # reuse keyboard
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{event_id}"),
                            InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{event_id}")
                        ],
                        [
                            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{event_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    if processing_message:
                        await processing_message.edit_text(result['message'], reply_markup=reply_markup, parse_mode='Markdown')
                    else:
                        await update.message.reply_text(result['message'], reply_markup=reply_markup, parse_mode='Markdown')
                    return

                response = f"✅ {result['message']}"
                if result.get('event_link'):
                    response += f"\n\n🔗 <a href=\"{result['event_link']}\">Ссылка на событие</a>"
                
                # Используем HTML parse_mode для корректной обработки ссылок
                if processing_message:
                    await processing_message.edit_text(response, parse_mode='HTML', disable_web_page_preview=True)
                else:
                    await update.message.reply_text(response, parse_mode='HTML', disable_web_page_preview=True)
            else:
                response = f"❌ {result['message']}"
                if processing_message:
                    await processing_message.edit_text(response)
                else:
                    await update.message.reply_text(response)

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
        if event_id not in self.pending_events:
            await query.edit_message_text("❌ Событие не найдено или уже обработано.")
            return
        pending = self.pending_events[event_id]

        try:
            if pending.get('type') == 'event':
                event = pending.get('payload')
                result = self.assistant_service.create_confirmed_event(event)
            elif pending.get('type') == 'task':
                task = pending.get('payload')
                result = self.assistant_service.create_confirmed_task(task)
            else:
                await query.edit_message_text("❌ Неподдерживаемый тип для подтверждения.")
                return

            if result.get('success'):
                response = f"✅ {result['message']}"
                if result.get('event_link'):
                    response += f"\n\n🔗 <a href=\"{result['event_link']}\">Ссылка на событие</a>"
            else:
                response = f"❌ {result['message']}"

            # Используем HTML parse_mode для корректной обработки ссылок, но если в ответе есть неподдерживаемые теги — отправляем plain text
            try:
                await query.edit_message_text(response, parse_mode='HTML', disable_web_page_preview=True)
            except Exception:
                await query.edit_message_text(response)

            # Удаляем элемент из ожидающих
            del self.pending_events[event_id]

        except Exception as e:
            calendar_logger.log_error(e, "telegram_bot._confirm_event")
            await query.edit_message_text(f"❌ Произошла ошибка при создании: {str(e)}")

    async def _cancel_event(self, query, event_id: str):
        """Отмена создания события"""
        if event_id in self.pending_events:
            del self.pending_events[event_id]
        
        await query.edit_message_text("❌ Создание события отменено.")

    async def _edit_event(self, query, event_id: str):
        """Редактирование события"""
        if event_id not in self.pending_events:
            await query.edit_message_text("❌ Событие не найдено или уже обработано.")
            return

        pending = self.pending_events[event_id]
        event = pending.get("payload")
        if event is None:
            await query.edit_message_text("❌ Событие не найдено или уже обработано.")
            del self.pending_events[event_id]
            return
        
        # Формируем сообщение с данными для редактирования
        edit_message = f"""✏️ **Редактирование события**

Скопируйте, исправьте и отправьте данные в следующем формате:

```
Название: {event.title}
Время: {event.start_time.strftime("%d.%m.%Y %H:%M")}"""

        if event.duration_minutes:
            edit_message += f"\nДлительность: {event.duration_minutes} минут"
        elif event.end_time:
            edit_message += f"\nОкончание: {event.end_time.strftime('%H:%M')}"

        if event.description:
            edit_message += f"\nОписание: {event.description}"

        edit_message += "\n```\n\nИли напишите новый запрос заново."

        await query.edit_message_text(edit_message, parse_mode='Markdown')
        
        # Удаляем текущее событие из ожидающих
        del self.pending_events[event_id]

    def _is_research_followup(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False

        followup_hints = (
            "подробнее",
            "раскрой",
            "уточни",
            "деталь",
            "разверни",
            "пункт",
            "follow-up",
            "follow up",
            "more details",
            "elaborate",
        )
        return any(hint in normalized for hint in followup_hints)

    def _is_research_start(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False

        start_hints = (
            "исследуй",
            "найди информацию",
            "проведи исследование",
            "изучи тему",
            "deep dive",
            "investigate",
            "research",
        )
        return any(hint in normalized for hint in start_hints)

    def _looks_like_research_clarification(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False

        clarification_markers = (
            "меня интерес",
            "горизонт",
            "частичн",
            "полная замена",
            "в 3 года",
            "в 5 лет",
            "в 10 лет",
            "важна",
            "важно",
            "фокус",
            "сфокусируй",
        )
        return any(marker in normalized for marker in clarification_markers)

    def _should_force_research_followup(self, chat_id: str, user_text: str) -> bool:
        if not chat_id:
            return False

        context = self.research_store.get_active_context(chat_id)
        if not context:
            return False

        if self._is_research_followup(user_text):
            return True

        if self.research_store.is_clarification_pending(chat_id) and self._looks_like_research_clarification(user_text):
            return True

        return False

    def _should_force_research_new(self, chat_id: str, user_text: str) -> bool:
        if not self._is_research_start(user_text):
            return False

        context = self.research_store.get_active_context(chat_id)
        # If there is active context and user still uses start trigger, treat as follow-up/new topic
        # through research flow directly and avoid classification LLM call.
        return True if chat_id else False

    def _build_research_prompt(self, user_text: str, mode: str, context_payload: dict) -> str:
        if mode == "followup":
            brief = (context_payload.get("brief") or "").strip()
            findings = context_payload.get("findings") or []
            sources = context_payload.get("sources") or []

            top_findings = []
            for item in findings[:10]:
                claim = str(item.get("claim", "")).strip()
                status = str(item.get("status", "UNCERTAIN")).strip().upper()
                if claim:
                    top_findings.append(f"- [{status}] {claim}")

            top_sources = []
            for item in sources[:10]:
                url = str(item.get("url", "")).strip()
                if url:
                    top_sources.append(f"- {url}")

            return (
                "Используй skill `research-pipeline`.\n"
                "Это follow-up к предыдущему исследованию.\n\n"
                f"Вопрос пользователя: {user_text}\n"
                "Контекст предыдущего исследования:\n"
                f"- Краткий итог: {brief or 'нет данных'}\n"
                f"- Ключевые факты:\n{chr(10).join(top_findings) if top_findings else '- нет данных'}\n"
                f"- Источники:\n{chr(10).join(top_sources) if top_sources else '- нет данных'}\n\n"
                "Требования:\n"
                "1) Ответь по существующему контексту\n"
                "2) Если данных мало, добери только недостающее\n"
                "3) Отметь новые данные и новые источники отдельно\n"
            )

        return (
            "Используй skill `research-pipeline` из подключенных skills.\n"
            f"Тема: {user_text}\n\n"
            "Требования к ответу:\n"
            "1) Краткий итог (3-7 пунктов)\n"
            "2) Факты с метками [CONFIRMED]/[UNCERTAIN]/[NOT_FOUND]\n"
            "3) Список источников (URL)\n"
            "4) Что осталось непроверенным\n"
        )

    def _compact_research_answer(self, response_text: str) -> str:
        text = (response_text or "").strip()
        if not text:
            return "⚠️ Исследование завершилось пустым ответом."

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        compact_lines = lines[:18]
        compact = "\n".join(compact_lines)
        if len(lines) > len(compact_lines):
            compact += "\n\n...\nНапишите 'подробнее', чтобы углубиться по пунктам."

        if len(compact) > 2500:
            compact = compact[:2500].rstrip() + "\n\n...\nНапишите 'подробнее' для продолжения."
        return compact

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

    async def _handle_research_action(self, update: Update, user_message: str, result: dict, processing_message=None):
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        existing_context = self.research_store.get_active_context(chat_id) or {}

        mode = result.get("mode", "new")
        if self._is_research_followup(user_message) and existing_context:
            mode = "followup"
        if mode == "followup" and not existing_context:
            mode = "new"

        copilot_session_id = self.research_store.get_or_create_copilot_session_id(chat_id) if chat_id else ""
        wrapped_prompt = self._build_research_prompt(result.get("original_query", user_message), mode, existing_context)
        research_request = LLMRequest(
            content=wrapped_prompt,
            task_type="research",
            system_prompt="You are a precise research assistant. Follow the requested output structure exactly.",
            metadata={
                "is_private": True,
                "handler": "ResearchMode",
                "copilot_session_id": copilot_session_id,
            },
            text_only=True,
            allow_mcp_tools=True,
        )

        try:
            llm_response = self.assistant_service.inference.gateway.generate(research_request)
            response_text = (llm_response.content or "").strip()
            if not response_text:
                raise RuntimeError("empty response")

            compact_answer = self._compact_research_answer(response_text)

            try:
                self.research_store.save_turn(chat_id, user_message, response_text)
                self.research_store.save_artifacts(chat_id, response_text)
            except Exception as store_exc:
                calendar_logger.log_error(store_exc, "telegram_bot._handle_research_action.store")

            prefix = "🔎 Follow-up исследование" if mode == "followup" else "🔎 Исследование"
            outbound = f"{prefix}\n\n{compact_answer}"
            if processing_message:
                await processing_message.edit_text(outbound, disable_web_page_preview=True)
            else:
                await self._send_long_message(update.message, outbound)

        except Exception as exc:
            calendar_logger.log_error(exc, "telegram_bot._handle_research_action")
            fallback = (
                "⚠️ Не удалось выполнить research-запрос через skill/runtime. "
                "Проверьте авторизацию Copilot (`gh auth login`) и доступность skills."
            )
            if processing_message:
                await processing_message.edit_text(fallback)
            else:
                await update.message.reply_text(fallback)

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

