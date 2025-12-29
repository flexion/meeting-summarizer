"""Pytest configuration and shared fixtures."""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for tests.

    Yields:
        Path to temporary directory.
    """
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def sample_audio_data() -> bytes:
    """Provide sample audio data for testing.

    Returns:
        Sample audio bytes.
    """
    # Simple WAV header + silence (minimal valid WAV file)
    return b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x08\x00data\x00\x00\x00\x00"


@pytest.fixture
def sample_transcript() -> str:
    """Provide sample transcript text for testing.

    Returns:
        Sample meeting transcript.
    """
    return """
    Welcome everyone to today's meeting. We'll be discussing the Q4 roadmap.
    First, let's review our progress on the current sprint.
    John, can you give us an update on the API development?
    Sure, the REST API is about 80% complete. We should have it finished by Friday.
    That's great. Sarah, what about the frontend?
    The UI components are done, but we need to integrate them with the new API.
    Alright, let's make that a priority for next week.
    Any other items we need to discuss?
    """
