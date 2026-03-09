from __future__ import annotations

import unittest

from chat_application_service import ChatResponse
from voice_input_service import VoiceInputService


class FakeVoiceService:
    def __init__(self, voice_text: str | None = None, audio_text: str | None = None, loaded: bool = True):
        self.voice_text = voice_text
        self.audio_text = audio_text
        self.loaded = loaded

    def is_model_loaded(self) -> bool:
        return self.loaded

    async def transcribe_voice_message(self, voice_file):
        return self.voice_text

    async def transcribe_audio_file(self, audio_file, source_extension: str = "bin"):
        return self.audio_text


class FakeChatService:
    def __init__(self):
        self.calls = []

    def process_text(self, chat_id: str, user_id: str | None, message_id: int | None, user_message: str):
        self.calls.append((chat_id, user_id, message_id, user_message))
        return ChatResponse(text=f"handled:{user_message}")


class VoiceInputServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_is_model_loaded_delegates_to_voice_service(self):
        service = VoiceInputService(
            voice_service=FakeVoiceService(loaded=False),
            chat_service=FakeChatService(),
        )

        self.assertFalse(service.is_model_loaded())

    async def test_process_voice_message_transcribes_and_routes_text(self):
        chat_service = FakeChatService()
        service = VoiceInputService(
            voice_service=FakeVoiceService(voice_text="купить хлеб"),
            chat_service=chat_service,
        )

        result = await service.process_voice_message(
            chat_id="chat-1",
            user_id="user-1",
            username="tester",
            message_id=10,
            voice_file=object(),
        )

        self.assertEqual(result.transcription, "купить хлеб")
        self.assertEqual(result.chat_response.text, "handled:купить хлеб")
        self.assertEqual(chat_service.calls, [("chat-1", "user-1", 10, "купить хлеб")])

    async def test_process_audio_file_transcribes_and_routes_text(self):
        chat_service = FakeChatService()
        service = VoiceInputService(
            voice_service=FakeVoiceService(audio_text="оплатить счета"),
            chat_service=chat_service,
        )

        result = await service.process_audio_file(
            chat_id="chat-1",
            user_id="user-1",
            username="tester",
            message_id=12,
            audio_file=object(),
            source_extension="mp3",
            source_label="AUDIO_FILE",
        )

        self.assertEqual(result.transcription, "оплатить счета")
        self.assertEqual(result.chat_response.text, "handled:оплатить счета")
        self.assertEqual(chat_service.calls, [("chat-1", "user-1", 12, "оплатить счета")])

    async def test_multiple_requests_in_same_chat_are_forwarded_in_order(self):
        chat_service = FakeChatService()
        service = VoiceInputService(
            voice_service=FakeVoiceService(voice_text="первый запрос", audio_text="второй запрос"),
            chat_service=chat_service,
        )

        await service.process_voice_message(
            chat_id="chat-1",
            user_id="user-1",
            username="tester",
            message_id=20,
            voice_file=object(),
        )
        await service.process_audio_file(
            chat_id="chat-1",
            user_id="user-1",
            username="tester",
            message_id=21,
            audio_file=object(),
            source_extension="wav",
            source_label="AUDIO_FILE",
        )

        self.assertEqual(
            chat_service.calls,
            [
                ("chat-1", "user-1", 20, "первый запрос"),
                ("chat-1", "user-1", 21, "второй запрос"),
            ],
        )

    async def test_process_audio_file_raises_when_transcription_is_empty(self):
        service = VoiceInputService(
            voice_service=FakeVoiceService(audio_text=None),
            chat_service=FakeChatService(),
        )

        with self.assertRaisesRegex(ValueError, "Не удалось распознать речь из аудиофайла"):
            await service.process_audio_file(
                chat_id="chat-1",
                user_id="user-1",
                username="tester",
                message_id=11,
                audio_file=object(),
                source_extension="mp3",
                source_label="AUDIO_FILE",
            )


if __name__ == "__main__":
    unittest.main()