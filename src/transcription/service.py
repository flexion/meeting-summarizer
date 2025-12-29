"""Transcription service for converting speech to text."""

from pathlib import Path
from typing import Protocol


class TranscriptionResult:
    """Result of a transcription operation."""

    def __init__(self, text: str, confidence: float, language: str = "en") -> None:
        """Initialize transcription result.

        Args:
            text: Transcribed text.
            confidence: Confidence score (0.0 to 1.0).
            language: Detected or specified language code.
        """
        self.text = text
        self.confidence = confidence
        self.language = language


class TranscriptionProvider(Protocol):
    """Protocol for transcription service providers."""

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        """Transcribe audio file to text.

        Args:
            audio_path: Path to audio file.

        Returns:
            Transcription result.
        """
        ...


class TranscriptionService:
    """Service for transcribing audio files."""

    def __init__(self, provider: TranscriptionProvider) -> None:
        """Initialize transcription service.

        Args:
            provider: Transcription provider implementation.
        """
        self.provider = provider

    def transcribe_file(self, audio_path: Path) -> TranscriptionResult:
        """Transcribe an audio file.

        Args:
            audio_path: Path to the audio file.

        Returns:
            Transcription result containing text and metadata.

        Raises:
            FileNotFoundError: If audio file doesn't exist.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        return self.provider.transcribe(audio_path)
