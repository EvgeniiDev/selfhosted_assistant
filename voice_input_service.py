from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from chat_application_service import ChatApplicationService, ChatResponse
from logger import calendar_logger

if TYPE_CHECKING:
    from voice_service import VoiceService


@dataclass(slots=True)
class VoiceInputResult:
    transcription: str
    chat_response: ChatResponse


class VoiceInputService:
    """Application-layer orchestration for audio transcription followed by chat handling."""

    def __init__(
        self,
        voice_service: VoiceService,
        chat_service: ChatApplicationService,
    ) -> None:
        self.voice_service = voice_service
        self.chat_service = chat_service

    def is_model_loaded(self) -> bool:
        return self.voice_service.is_model_loaded()

    async def process_voice_message(
        self,
        chat_id: str,
        user_id: str | None,
        username: str | None,
        message_id: int | None,
        voice_file: Any,
    ) -> VoiceInputResult:
        transcription = await self.voice_service.transcribe_voice_message(voice_file)
        return self._build_result(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            message_id=message_id,
            transcription=transcription,
            source_label="VOICE",
            failure_message="Не удалось распознать речь. Попробуйте записать сообщение заново.",
        )

    async def process_audio_file(
        self,
        chat_id: str,
        user_id: str | None,
        username: str | None,
        message_id: int | None,
        audio_file: Any,
        source_extension: str,
        source_label: str,
    ) -> VoiceInputResult:
        transcription = await self.voice_service.transcribe_audio_file(
            audio_file,
            source_extension=source_extension,
        )
        return self._build_result(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            message_id=message_id,
            transcription=transcription,
            source_label=source_label,
            failure_message="Не удалось распознать речь из аудиофайла. Попробуйте другой файл.",
        )

    def _build_result(
        self,
        chat_id: str,
        user_id: str | None,
        username: str | None,
        message_id: int | None,
        transcription: str | None,
        source_label: str,
        failure_message: str,
    ) -> VoiceInputResult:
        if not transcription:
            raise ValueError(failure_message)

        calendar_logger.log_user_request(user_id, username, f"[{source_label}] {transcription}")
        chat_response = self.chat_service.process_text(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            user_message=transcription,
        )
        return VoiceInputResult(
            transcription=transcription,
            chat_response=chat_response,
        )
