import io
import torch
import os
from typing import Any, Optional
import time
import tempfile
from pydub import AudioSegment
from telegram import File

import gigaam


from logger import calendar_logger


class VoiceService:
    """Сервис для обработки голосовых сообщений"""
    
    def __init__(self, device: str = "cpu"):
        """
        Инициализация сервиса обработки голоса
        
        Args:
            device: устройство для инференса ("cpu" или "cuda")
        """
        self.device = device
        self.model_name = os.getenv("GIGAAM_MODEL_NAME", "v3_e2e_rnnt")
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Загружает модель GigaAM для распознавания речи"""
        try:
            self.model = gigaam.load_model(
                self.model_name,
                device=self.device
            )
            calendar_logger.info(f"Модель GigaAM успешно загружена: {self.model_name}")
        except Exception as e:
            calendar_logger.log_error(e, "voice_service._load_model")
            print(f"Ошибка загрузки модели GigaAM: {str(e)}")
            self.model = None

    def _transcribe_with_temp_wav(self, audio_data: torch.Tensor, use_shortform: bool):
        import torchaudio

        if self.model is None:
            raise RuntimeError("GigaAM model is not loaded")

        model = self.model
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            torchaudio.save(tmp_path, audio_data.unsqueeze(0).cpu(), 16000)

            if use_shortform:
                return model.transcribe(tmp_path)
            return model.transcribe_longform(tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _run_transcription(self, audio_data: torch.Tensor, use_shortform: bool):
        if self.model is None:
            raise RuntimeError("GigaAM model is not loaded")

        return self._transcribe_with_temp_wav(audio_data, use_shortform)

    def _extract_text_fragments(self, value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []

        if isinstance(value, dict):
            fragments: list[str] = []

            for key in (
                "transcription", "text", "utterance", "sentence", "content", "result", "prediction"
            ):
                if key in value:
                    fragments.extend(self._extract_text_fragments(value.get(key)))

            for key in (
                "segments", "items", "hypotheses", "alternatives", "words", "chunks", "results"
            ):
                if key in value:
                    fragments.extend(self._extract_text_fragments(value.get(key)))

            if not fragments:
                for nested in value.values():
                    fragments.extend(self._extract_text_fragments(nested))

            return [frag for frag in fragments if frag]

        if isinstance(value, (list, tuple)):
            fragments: list[str] = []
            for item in value:
                fragments.extend(self._extract_text_fragments(item))
            return [frag for frag in fragments if frag]

        return []

    def _normalize_transcription_result(self, result) -> str:
        fragments = self._extract_text_fragments(result)
        if fragments:
            seen = set()
            unique_fragments = []
            for fragment in fragments:
                if fragment not in seen:
                    seen.add(fragment)
                    unique_fragments.append(fragment)
            return " ".join(unique_fragments).strip()

        return str(result).strip() if result is not None else ""
    
    async def transcribe_voice_message(self, voice_file: File) -> Optional[str]:
        return await self.transcribe_audio_file(voice_file, source_extension="ogg")

    async def transcribe_audio_file(self, audio_file: File, source_extension: str = "bin") -> Optional[str]:
        """
        Транскрибирует аудиофайл в текст
        
        Args:
            audio_file: объект файла аудио из Telegram
            source_extension: расширение исходного файла (для отладочного сохранения)
            
        Returns:
            str: транскрибированный текст или None в случае ошибки
        """
        file_bytes = None
        safe_ext = (source_extension or "bin").lower().strip().lstrip(".")
        if not safe_ext or any(ch in safe_ext for ch in "\\/:*?\"<>|"):
            safe_ext = "bin"

        try:
            # Скачиваем файл в память
            file_bytes = await audio_file.download_as_bytearray()

            # Конвертируем в аудио формат, который понимает модель
            audio_data = self._convert_audio_to_wav(file_bytes, source_extension=safe_ext)

            # Короткая речь (<=25с) — однопроходный transcribe, иначе longform
            LONGFORM_THRESHOLD_SAMPLES = 25 * 16000
            use_shortform = int(audio_data.numel()) <= LONGFORM_THRESHOLD_SAMPLES

            result = self._run_transcription(audio_data, use_shortform)
            transcription = self._normalize_transcription_result(result)

            calendar_logger.info(
                f"Аудио транскрибировано ({safe_ext}): {transcription if len(transcription) < 256 else transcription[:253] + '...'}"
            )

            # Если пустая транскрипция — пробуем альтернативный режим
            if not transcription:
                try:
                    fallback = self._run_transcription(audio_data, use_shortform=not use_shortform)
                    fallback_text = self._normalize_transcription_result(fallback)
                    if fallback_text:
                        calendar_logger.info(
                            f"Аудио транскрибировано через fallback ({'shortform' if not use_shortform else 'longform'}): "
                            f"{fallback_text if len(fallback_text) < 256 else fallback_text[:253] + '...'}"
                        )
                        return fallback_text
                except Exception as fb_err:
                    calendar_logger.log_error(fb_err, "voice_service.transcribe_audio_file.fallback")

            # Если всё равно пусто — сохраняем вход для отладки
            if not transcription:
                try:
                    dbg_dir = os.path.join(os.path.dirname(__file__), "debug_audio")
                    os.makedirs(dbg_dir, exist_ok=True)
                    ts = int(time.time())
                    raw_path = os.path.join(dbg_dir, f"input_{ts}.{safe_ext}")
                    wav_path = os.path.join(dbg_dir, f"waveform_{ts}.pt")
                    with open(raw_path, "wb") as f:
                        f.write(file_bytes)
                    torch.save(audio_data, wav_path)
                except Exception as save_err:
                    calendar_logger.log_error(save_err, "voice_service.transcribe_audio_file.save_debug")

            return transcription if transcription else None

        except Exception as e:
            calendar_logger.log_error(e, "voice_service.transcribe_audio_file")
            # Пытаемся сохранить входные данные на случай ошибки
            try:
                if file_bytes is not None:
                    dbg_dir = os.path.join(os.path.dirname(__file__), "debug_audio")
                    os.makedirs(dbg_dir, exist_ok=True)
                    ts = int(time.time())
                    raw_path = os.path.join(dbg_dir, f"error_input_{ts}.{safe_ext}")
                    with open(raw_path, "wb") as f:
                        f.write(file_bytes)
            except Exception as save_err:
                calendar_logger.log_error(save_err, "voice_service.transcribe_audio_file.save_error_input")
            return None
    
    def _convert_audio_to_wav(self, audio_bytes: bytearray, source_extension: str = "bin") -> torch.Tensor:
        """
        Конвертирует входное аудио в WAV формат и возвращает torch.Tensor
        
        Args:
            audio_bytes: байты входного аудиофайла
            
        Returns:
            torch.Tensor: аудио данные
        """
        import torchaudio
        ext = (source_extension or "bin").lower().strip().lstrip(".")
        if not ext or any(ch in ext for ch in "\\/:*?\"<>|"):
            ext = "bin"
        
        try:
            waveform = None
            sample_rate = None

            tmp_audio_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp_audio:
                    tmp_audio_path = tmp_audio.name
                    tmp_audio.write(bytes(audio_bytes))

                waveform, sample_rate = torchaudio.load(tmp_audio_path)
            finally:
                if tmp_audio_path and os.path.exists(tmp_audio_path):
                    try:
                        os.remove(tmp_audio_path)
                    except OSError:
                        pass

            if waveform is None or sample_rate is None:
                raise RuntimeError("Не удалось загрузить аудио через torchaudio")
            
            # Преобразуем в моно если нужно
            if waveform.shape[0] > 1:
                waveform = torch.mean(waveform, dim=0, keepdim=True)
            
            # Убираем лишнюю размерность
            waveform = waveform.squeeze(0)
            
            # Ресемплируем до 16kHz для модели
            if sample_rate != 16000:
                resampler = torchaudio.transforms.Resample(sample_rate, 16000)
                waveform = resampler(waveform)

            # Нормализуем значения в допустимый диапазон [-1, 1]
            if waveform.dtype.is_floating_point:
                clipped = waveform.clamp_(-1.0, 1.0)
                waveform = clipped
            
            calendar_logger.info(f"Аудио конвертировано: sample_rate={sample_rate}, shape={waveform.shape}")
            return waveform
                
        except Exception as e:
            calendar_logger.warning(f"torchaudio decode failed for {ext}, fallback to pydub: {str(e)}")
            try:
                source_buffer = io.BytesIO(audio_bytes)
                file_format = ext if ext in {"mp3", "wav", "ogg"} else None
                segment = AudioSegment.from_file(source_buffer, format=file_format)
                segment = segment.set_channels(1).set_frame_rate(16000)

                wav_buffer = io.BytesIO()
                segment.export(wav_buffer, format="wav")
                wav_buffer.seek(0)

                waveform, sample_rate = torchaudio.load(wav_buffer)

                if waveform.shape[0] > 1:
                    waveform = torch.mean(waveform, dim=0, keepdim=True)

                waveform = waveform.squeeze(0)

                if sample_rate != 16000:
                    resampler = torchaudio.transforms.Resample(sample_rate, 16000)
                    waveform = resampler(waveform)

                if waveform.dtype.is_floating_point:
                    waveform = waveform.clamp_(-1.0, 1.0)

                calendar_logger.info(f"Аудио конвертировано через pydub fallback: sample_rate={sample_rate}, shape={waveform.shape}")
                return waveform
            except Exception as fallback_error:
                calendar_logger.log_error(fallback_error, "voice_service._convert_audio_to_wav.fallback")
                raise

    
    def is_model_loaded(self) -> bool:
        """Проверяет, загружена ли модель"""
        return self.model is not None
