"""Tests for storage manager."""

from pathlib import Path

import pytest

from src.storage.manager import StorageManager


def test_storage_manager_initialization(temp_dir: Path) -> None:
    """Test storage manager creates necessary directories."""
    manager = StorageManager(temp_dir)

    assert manager.audio_path.exists()
    assert manager.transcript_path.exists()
    assert manager.audio_path.is_dir()
    assert manager.transcript_path.is_dir()


def test_save_audio(temp_dir: Path, sample_audio_data: bytes) -> None:
    """Test saving audio data."""
    manager = StorageManager(temp_dir)
    filename = "test_audio.wav"

    saved_path = manager.save_audio(sample_audio_data, filename)

    assert saved_path.exists()
    assert saved_path.name == filename
    assert saved_path.read_bytes() == sample_audio_data


def test_save_and_load_transcript(temp_dir: Path, sample_transcript: str) -> None:
    """Test saving and loading transcript."""
    manager = StorageManager(temp_dir)
    filename = "meeting_001"

    saved_path = manager.save_transcript(sample_transcript, filename)
    loaded_transcript = manager.load_transcript(filename)

    assert saved_path.exists()
    assert loaded_transcript == sample_transcript


def test_load_nonexistent_transcript(temp_dir: Path) -> None:
    """Test loading transcript that doesn't exist raises error."""
    manager = StorageManager(temp_dir)

    with pytest.raises(FileNotFoundError):
        manager.load_transcript("nonexistent")


def test_list_audio_files(temp_dir: Path, sample_audio_data: bytes) -> None:
    """Test listing audio files."""
    manager = StorageManager(temp_dir)

    # Save multiple audio files
    manager.save_audio(sample_audio_data, "audio1.wav")
    manager.save_audio(sample_audio_data, "audio2.wav")

    audio_files = manager.list_audio_files()

    assert len(audio_files) == 2
    assert "audio1.wav" in audio_files
    assert "audio2.wav" in audio_files


def test_list_transcripts(temp_dir: Path, sample_transcript: str) -> None:
    """Test listing transcripts."""
    manager = StorageManager(temp_dir)

    # Save multiple transcripts
    manager.save_transcript(sample_transcript, "meeting_001")
    manager.save_transcript(sample_transcript, "meeting_002")

    transcripts = manager.list_transcripts()

    assert len(transcripts) == 2
    assert "meeting_001" in transcripts
    assert "meeting_002" in transcripts


def test_save_summary(temp_dir: Path) -> None:
    """Test saving summary data."""
    manager = StorageManager(temp_dir)
    summary_data = {
        "brief": "Discussion about Q4 roadmap",
        "key_points": ["API development at 80%", "Frontend integration needed"],
        "action_items": ["Complete API by Friday", "Prioritize frontend integration"],
    }

    saved_path = manager.save_summary(summary_data, "meeting_001")

    assert saved_path.exists()
    assert saved_path.suffix == ".json"
