"""Audio format conversion and processing for Whisper compatibility."""

from __future__ import annotations

import logging
import os
import threading
import wave
from datetime import datetime

import numpy as np
from scipy import signal

from playwright_bot.audio.exceptions import AudioProcessingError

logger = logging.getLogger(__name__)

# Whisper audio format constants
WHISPER_SAMPLE_RATE = 16000  # 16kHz
WHISPER_CHANNELS = 1  # Mono
WHISPER_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes


class AudioProcessor:
    """Converts browser audio to Whisper-compatible format.

    This class receives audio data from the browser (typically 48kHz, stereo, float32)
    and converts it to the format expected by faster-whisper (16kHz, mono, int16 PCM).
    Audio is written incrementally to a WAV file for crash safety.

    Usage:
        processor = AudioProcessor(output_dir="transcripts")
        processor.start()

        # Called by AudioCapturer callback
        processor.process(audio_bytes, source_rate=48000, source_channels=2)

        wav_path, duration = processor.stop()
    """

    def __init__(
        self,
        output_dir: str = "transcripts",
        target_rate: int = WHISPER_SAMPLE_RATE,
    ) -> None:
        """Initialize the audio processor.

        Args:
            output_dir: Directory to save WAV files
            target_rate: Target sample rate (default 16kHz for Whisper)
        """
        self._output_dir = output_dir
        self._target_rate = target_rate

        self._wav_path: str | None = None
        self._wav_file: wave.Wave_write | None = None
        self._processing = False
        self._lock = threading.Lock()

        self._total_samples = 0
        self._start_time: datetime | None = None

        # Resampling state for continuous streams
        self._resample_buffer: np.ndarray | None = None

    def start(self) -> str:
        """Start processing and create output WAV file.

        Returns:
            Path to the WAV file being written

        Raises:
            AudioProcessingError: If processing is already started or file creation fails
        """
        with self._lock:
            if self._processing:
                raise AudioProcessingError("Audio processing already started")

            # Ensure output directory exists
            os.makedirs(self._output_dir, exist_ok=True)

            # Create WAV file with timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"recording_{timestamp}.wav"
            self._wav_path = os.path.join(self._output_dir, filename)

            try:
                self._wav_file = wave.open(self._wav_path, "wb")
                self._wav_file.setnchannels(WHISPER_CHANNELS)
                self._wav_file.setsampwidth(WHISPER_SAMPLE_WIDTH)
                self._wav_file.setframerate(self._target_rate)

                self._processing = True
                self._total_samples = 0
                self._start_time = datetime.now()
                self._resample_buffer = None

                logger.info(f"Audio processor started, writing to: {self._wav_path}")
                return self._wav_path

            except Exception as e:
                raise AudioProcessingError(f"Failed to create WAV file: {e}") from e

    def process(
        self,
        audio_data: bytes,
        source_rate: int,
        source_channels: int = 2,
    ) -> None:
        """Process incoming audio data and write to WAV file.

        Converts audio from source format (typically 48kHz stereo float32)
        to Whisper format (16kHz mono int16).

        Args:
            audio_data: Raw audio bytes (Float32Array from browser)
            source_rate: Source sample rate in Hz
            source_channels: Number of source channels (1 or 2)

        Raises:
            AudioProcessingError: If processing fails
        """
        with self._lock:
            if not self._processing or not self._wav_file:
                return

            try:
                # Decode Float32 array from bytes
                samples = np.frombuffer(audio_data, dtype=np.float32)

                if len(samples) == 0:
                    return

                # Convert stereo to mono
                if source_channels == 2:
                    # Interleaved stereo: [L0, R0, L1, R1, ...]
                    left = samples[0::2]
                    right = samples[1::2]
                    mono = (left + right) / 2
                else:
                    mono = samples

                # Resample if needed
                if source_rate != self._target_rate:
                    mono = self._resample(mono, source_rate, self._target_rate)

                # Convert float32 [-1, 1] to int16 [-32768, 32767]
                mono = np.clip(mono, -1.0, 1.0)
                int16_data = (mono * 32767).astype(np.int16)

                # Write to WAV file
                self._wav_file.writeframes(int16_data.tobytes())
                self._total_samples += len(int16_data)

            except Exception as e:
                logger.error(f"Error processing audio: {e}")
                raise AudioProcessingError(f"Failed to process audio: {e}") from e

    def _resample(
        self,
        audio: np.ndarray,
        source_rate: int,
        target_rate: int,
    ) -> np.ndarray:
        """Resample audio to target sample rate.

        Uses scipy.signal.resample for high-quality resampling.

        Args:
            audio: Input audio samples
            source_rate: Source sample rate
            target_rate: Target sample rate

        Returns:
            Resampled audio
        """
        if source_rate == target_rate:
            return audio

        # Calculate target number of samples
        num_samples = int(len(audio) * target_rate / source_rate)

        if num_samples == 0:
            return np.array([], dtype=np.float32)

        # Use scipy resample for high quality
        resampled = signal.resample(audio, num_samples)

        return resampled.astype(np.float32)

    def stop(self) -> tuple[str, float] | None:
        """Stop processing and close the WAV file.

        Returns:
            Tuple of (wav_path, duration_seconds) or None if not processing
        """
        with self._lock:
            if not self._processing:
                return None

            self._processing = False

            wav_path = self._wav_path
            duration = self.duration

            # Close WAV file
            if self._wav_file:
                try:
                    self._wav_file.close()
                except Exception as e:
                    logger.warning(f"Error closing WAV file: {e}")
                finally:
                    self._wav_file = None

            logger.info(f"Audio processor stopped. Duration: {duration:.2f}s, Path: {wav_path}")

            return wav_path, duration

    @property
    def duration(self) -> float:
        """Get the duration of recorded audio in seconds.

        Returns:
            Duration in seconds
        """
        if self._target_rate > 0:
            return self._total_samples / self._target_rate
        return 0.0

    @property
    def wav_path(self) -> str | None:
        """Get the path to the WAV file.

        Returns:
            Path to WAV file or None if not started
        """
        return self._wav_path

    @property
    def is_processing(self) -> bool:
        """Check if currently processing audio.

        Returns:
            True if processing
        """
        return self._processing

    @property
    def total_samples(self) -> int:
        """Get the total number of samples written.

        Returns:
            Total samples written to WAV file
        """
        return self._total_samples


def convert_audio_chunk(
    audio_data: bytes,
    source_rate: int = 48000,
    target_rate: int = 16000,
    source_channels: int = 2,
) -> bytes:
    """Convert a single audio chunk to Whisper format.

    Standalone function for one-shot conversion.

    Args:
        audio_data: Raw audio bytes (Float32Array from browser)
        source_rate: Source sample rate in Hz
        target_rate: Target sample rate in Hz
        source_channels: Number of source channels

    Returns:
        Converted audio as int16 bytes
    """
    # Decode Float32 array
    samples = np.frombuffer(audio_data, dtype=np.float32)

    if len(samples) == 0:
        return b""

    # Convert stereo to mono
    if source_channels == 2:
        left = samples[0::2]
        right = samples[1::2]
        mono = (left + right) / 2
    else:
        mono = samples

    # Resample
    if source_rate != target_rate:
        num_samples = int(len(mono) * target_rate / source_rate)
        if num_samples > 0:
            mono = signal.resample(mono, num_samples)
        else:
            return b""

    # Convert to int16
    mono = np.clip(mono, -1.0, 1.0)
    int16_data = (mono * 32767).astype(np.int16)

    return int16_data.tobytes()
