"""Tests for audio processor."""

from pathlib import Path

import pytest

from src.audio.processor import AudioProcessor


def test_audio_processor_initialization() -> None:
    """Test audio processor initializes with correct sample rate."""
    processor = AudioProcessor(sample_rate=16000)
    assert processor.sample_rate == 16000

    processor_custom = AudioProcessor(sample_rate=44100)
    assert processor_custom.sample_rate == 44100


def test_load_audio_file_not_found() -> None:
    """Test loading non-existent audio file raises error."""
    processor = AudioProcessor()
    fake_path = Path("/nonexistent/path/audio.wav")

    with pytest.raises(FileNotFoundError):
        processor.load_audio(fake_path)


def test_load_audio_success(temp_dir: Path, sample_audio_data: bytes) -> None:
    """Test successfully loading audio file."""
    processor = AudioProcessor()
    audio_file = temp_dir / "test.wav"
    audio_file.write_bytes(sample_audio_data)

    loaded_data = processor.load_audio(audio_file)

    assert loaded_data == sample_audio_data


def test_convert_format(sample_audio_data: bytes) -> None:
    """Test audio format conversion (placeholder)."""
    processor = AudioProcessor()
    converted = processor.convert_format(sample_audio_data, "mp3")

    # Currently returns same data (placeholder implementation)
    assert converted == sample_audio_data


def test_normalize_audio(sample_audio_data: bytes) -> None:
    """Test audio normalization (placeholder)."""
    processor = AudioProcessor()
    normalized = processor.normalize_audio(sample_audio_data)

    # Currently returns same data (placeholder implementation)
    assert normalized == sample_audio_data
