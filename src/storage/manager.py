"""Storage manager for persisting audio, transcripts, and summaries."""

import json
from pathlib import Path
from typing import Any


class StorageManager:
    """Manage storage of audio files, transcripts, and summaries."""

    def __init__(self, base_path: Path) -> None:
        """Initialize storage manager.

        Args:
            base_path: Base directory for data storage.
        """
        self.base_path = Path(base_path)
        self.audio_path = self.base_path / "audio"
        self.transcript_path = self.base_path / "transcripts"

        # Create directories if they don't exist
        self.audio_path.mkdir(parents=True, exist_ok=True)
        self.transcript_path.mkdir(parents=True, exist_ok=True)

    def save_audio(self, audio_data: bytes, filename: str) -> Path:
        """Save audio data to storage.

        Args:
            audio_data: Raw audio data.
            filename: Name for the audio file.

        Returns:
            Path to saved audio file.
        """
        file_path = self.audio_path / filename
        with open(file_path, "wb") as f:
            f.write(audio_data)
        return file_path

    def save_transcript(self, transcript: str, filename: str) -> Path:
        """Save transcript to storage.

        Args:
            transcript: Transcript text.
            filename: Name for the transcript file.

        Returns:
            Path to saved transcript file.
        """
        file_path = self.transcript_path / f"{filename}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(transcript)
        return file_path

    def save_summary(self, summary_data: dict[str, Any], filename: str) -> Path:
        """Save summary data to storage.

        Args:
            summary_data: Summary data as a dictionary.
            filename: Name for the summary file.

        Returns:
            Path to saved summary file.
        """
        file_path = self.transcript_path / f"{filename}_summary.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
        return file_path

    def load_transcript(self, filename: str) -> str:
        """Load a transcript from storage.

        Args:
            filename: Name of the transcript file.

        Returns:
            Transcript text.

        Raises:
            FileNotFoundError: If transcript doesn't exist.
        """
        file_path = self.transcript_path / f"{filename}.txt"
        if not file_path.exists():
            raise FileNotFoundError(f"Transcript not found: {filename}")

        with open(file_path, encoding="utf-8") as f:
            return f.read()

    def list_audio_files(self) -> list[str]:
        """List all audio files in storage.

        Returns:
            List of audio filenames.
        """
        return [f.name for f in self.audio_path.iterdir() if f.is_file()]

    def list_transcripts(self) -> list[str]:
        """List all transcripts in storage.

        Returns:
            List of transcript filenames (without .txt extension).
        """
        return [
            f.stem for f in self.transcript_path.iterdir() if f.is_file() and f.suffix == ".txt"
        ]
