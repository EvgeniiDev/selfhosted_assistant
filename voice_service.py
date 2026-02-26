import io
import torch
import os
from typing import Union, Optional
import time
import tempfile
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
    
    async def transcribe_voice_message(self, voice_file: File) -> Optional[str]:
        """
        Транскрибирует голосовое сообщение в текст
        
        Args:
            voice_file: объект файла голосового сообщения из Telegram
            
        Returns:
            str: транскрибированный текст или None в случае ошибки
        """
        file_bytes = None
        try:
            # Скачиваем файл в память
            file_bytes = await voice_file.download_as_bytearray()

            # Конвертируем в аудио формат, который понимает модель
            audio_data = self._convert_ogg_to_wav(file_bytes)

            # Короткая речь (<=25с) — однопроходный transcribe, иначе longform
            LONGFORM_THRESHOLD_SAMPLES = 25 * 16000
            use_shortform = int(audio_data.numel()) <= LONGFORM_THRESHOLD_SAMPLES

            result = self._run_transcription(audio_data, use_shortform)

            # GigaAM.transcribe_longform возвращает список сегментов
            if isinstance(result, list):
                segments = []
                for seg in result:
                    if isinstance(seg, dict):
                        text = seg.get("transcription")
                        if isinstance(text, str) and text.strip():
                            segments.append(text.strip())
                    elif isinstance(seg, str) and seg.strip():
                        segments.append(seg.strip())
                transcription = " ".join(segments).strip()
            elif isinstance(result, str):
                transcription = result.strip()
            else:
                transcription = str(result).strip() if result is not None else ""

            calendar_logger.info(
                f"Голосовое сообщение транскрибировано: {transcription if len(transcription) < 256 else transcription[:253] + '...'}"
            )

            # Если пустая транскрипция — пробуем fallback (shortform)
            if not transcription and not use_shortform:
                try:
                    fallback = self._run_transcription(audio_data, use_shortform=True)
                    if isinstance(fallback, str) and fallback.strip():
                        return fallback.strip()
                except Exception as fb_err:
                    calendar_logger.log_error(fb_err, "voice_service.transcribe_voice_message.fallback")

            # Если всё равно пусто — сохраняем вход для отладки
            if not transcription:
                try:
                    dbg_dir = os.path.join(os.path.dirname(__file__), "debug_audio")
                    os.makedirs(dbg_dir, exist_ok=True)
                    ts = int(time.time())
                    raw_path = os.path.join(dbg_dir, f"input_{ts}.ogg")
                    wav_path = os.path.join(dbg_dir, f"waveform_{ts}.pt")
                    with open(raw_path, "wb") as f:
                        f.write(file_bytes)
                    torch.save(audio_data, wav_path)
                except Exception as save_err:
                    calendar_logger.log_error(save_err, "voice_service.transcribe_voice_message.save_debug")

            return transcription if transcription else None

        except Exception as e:
            calendar_logger.log_error(e, "voice_service.transcribe_voice_message")
            # Пытаемся сохранить входные данные на случай ошибки
            try:
                if file_bytes is not None:
                    dbg_dir = os.path.join(os.path.dirname(__file__), "debug_audio")
                    os.makedirs(dbg_dir, exist_ok=True)
                    ts = int(time.time())
                    raw_path = os.path.join(dbg_dir, f"error_input_{ts}.ogg")
                    with open(raw_path, "wb") as f:
                        f.write(file_bytes)
            except Exception as save_err:
                calendar_logger.log_error(save_err, "voice_service.transcribe_voice_message.save_error_input")
            return None
    
    def _convert_ogg_to_wav(self, ogg_bytes: bytearray) -> torch.Tensor:
        """
        Конвертирует OGG аудио в WAV формат и возвращает torch.Tensor
        
        Args:
            ogg_bytes: байты OGG файла
            
        Returns:
            torch.Tensor: аудио данные
        """
        import torchaudio
        
        try:
            # Создаем BytesIO объект из байтов
            audio_buffer = io.BytesIO(ogg_bytes)
            
            # Загружаем аудио файл напрямую из памяти
            waveform, sample_rate = torchaudio.load(audio_buffer)
            
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
            calendar_logger.log_error(e, "voice_service._convert_ogg_to_wav")
            raise

    
    def is_model_loaded(self) -> bool:
        """Проверяет, загружена ли модель"""
        return self.model is not None
