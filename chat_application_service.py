from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from assistant_service import AssistantService
from logger import calendar_logger
from research_service import ResearchService


@dataclass(slots=True)
class PendingConfirmation:
    kind: str
    payload: Any


@dataclass(slots=True)
class ChatResponse:
    text: str
    parse_mode: str | None = None
    disable_web_page_preview: bool = False
    needs_confirmation: bool = False
    pending_id: str = ""


class ChatApplicationService:
    """Application service for chat turns, independent from Telegram transport objects."""

    def __init__(
        self,
        assistant_service: AssistantService | None = None,
        research_service: ResearchService | None = None,
    ) -> None:
        self.assistant_service = assistant_service or AssistantService()
        self.research_service = research_service or ResearchService(self.assistant_service.inference.gateway)
        self.pending_confirmations: dict[str, PendingConfirmation] = {}

    def process_text(
        self,
        chat_id: str,
        user_id: str | None,
        message_id: int | None,
        user_message: str,
    ) -> ChatResponse:
        try:
            if self.research_service.should_start_new(chat_id, user_message):
                return self._execute_research(chat_id, user_message, mode_hint="new")

            if self.research_service.should_followup(chat_id, user_message):
                return self._execute_research(chat_id, user_message, mode_hint="followup")

            result = self.assistant_service.process_user_request(user_message)
            if not result.get("success"):
                return ChatResponse(text=f"❌ {result['message']}")

            action = result.get("action")
            if action == "confirm":
                pending_id = self._build_pending_id(user_id, message_id)
                self.pending_confirmations[pending_id] = PendingConfirmation(
                    kind="event",
                    payload=result["event"],
                )
                return ChatResponse(
                    text=result["message"],
                    parse_mode="Markdown",
                    needs_confirmation=True,
                    pending_id=pending_id,
                )

            if action == "confirm_task":
                pending_id = self._build_pending_id(user_id, message_id)
                self.pending_confirmations[pending_id] = PendingConfirmation(
                    kind="task",
                    payload=result["task"],
                )
                return ChatResponse(
                    text=result["message"],
                    parse_mode="Markdown",
                    needs_confirmation=True,
                    pending_id=pending_id,
                )

            if action == "note":
                return ChatResponse(text=result["message"], parse_mode="Markdown")

            if action == "list_notes":
                return ChatResponse(text=result["message"], parse_mode="Markdown")

            if action == "research":
                return self._execute_research(
                    chat_id,
                    result.get("original_query", user_message),
                    mode_hint=result.get("mode", "new"),
                )

            text = f"✅ {result['message']}"
            if result.get("event_link"):
                text += f"\n\n🔗 <a href=\"{result['event_link']}\">Ссылка на событие</a>"
            return ChatResponse(
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        except Exception as exc:
            calendar_logger.log_error(exc, "chat_application_service.process_text")
            return ChatResponse(text=f"❌ Произошла ошибка: {str(exc)}")

    def confirm_pending(self, pending_id: str) -> ChatResponse:
        pending = self.pending_confirmations.get(pending_id)
        if pending is None:
            return ChatResponse(text="❌ Событие не найдено или уже обработано.")

        try:
            if pending.kind == "event":
                result = self.assistant_service.create_confirmed_event(pending.payload)
            elif pending.kind == "task":
                result = self.assistant_service.create_confirmed_task(pending.payload)
            else:
                return ChatResponse(text="❌ Неподдерживаемый тип для подтверждения.")

            self.pending_confirmations.pop(pending_id, None)

            if result.get("success"):
                text = f"✅ {result['message']}"
                if result.get("event_link"):
                    text += f"\n\n🔗 <a href=\"{result['event_link']}\">Ссылка на событие</a>"
                    return ChatResponse(
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                return ChatResponse(text=text)

            return ChatResponse(text=f"❌ {result['message']}")

        except Exception as exc:
            calendar_logger.log_error(exc, "chat_application_service.confirm_pending")
            return ChatResponse(text=f"❌ Произошла ошибка при создании: {str(exc)}")

    def cancel_pending(self, pending_id: str) -> ChatResponse:
        self.pending_confirmations.pop(pending_id, None)
        return ChatResponse(text="❌ Создание события отменено.")

    def edit_pending(self, pending_id: str) -> ChatResponse:
        pending = self.pending_confirmations.get(pending_id)
        if pending is None:
            return ChatResponse(text="❌ Событие не найдено или уже обработано.")

        self.pending_confirmations.pop(pending_id, None)

        if pending.kind == "event":
            event = pending.payload
            text = f"""✏️ **Редактирование события**

Скопируйте, исправьте и отправьте данные в следующем формате:

```
Название: {event.title}
Время: {event.start_time.strftime("%d.%m.%Y %H:%M")}"""

            if event.duration_minutes:
                text += f"\nДлительность: {event.duration_minutes} минут"
            elif event.end_time:
                text += f"\nОкончание: {event.end_time.strftime('%H:%M')}"

            if event.description:
                text += f"\nОписание: {event.description}"

            text += "\n```\n\nИли напишите новый запрос заново."
            return ChatResponse(text=text, parse_mode="Markdown")

        if pending.kind == "task":
            task = pending.payload
            text = f"""✏️ **Редактирование задачи**

Скопируйте, исправьте и отправьте данные в свободной форме:

```
Задача: {task.title}"""

            if task.due_time:
                text += f"\nСрок: {task.due_time.strftime('%d.%m.%Y %H:%M')}"
            if task.duration_minutes:
                text += f"\nДлительность: {task.duration_minutes} минут"
            if task.description:
                text += f"\nОписание: {task.description}"

            text += "\n```\n\nИли напишите новый запрос заново."
            return ChatResponse(text=text, parse_mode="Markdown")

        return ChatResponse(text="❌ Неподдерживаемый тип для редактирования.")

    def _execute_research(self, chat_id: str, user_text: str, mode_hint: str) -> ChatResponse:
        execution = self.research_service.execute(
            chat_id=chat_id,
            user_text=user_text,
            mode_hint=mode_hint,
        )
        return ChatResponse(
            text=execution.outbound_text,
            disable_web_page_preview=True,
        )

    def _build_pending_id(self, user_id: str | None, message_id: int | None) -> str:
        normalized_user_id = user_id or "unknown"
        normalized_message_id = str(message_id) if message_id is not None else "manual"
        return f"{normalized_user_id}_{normalized_message_id}"