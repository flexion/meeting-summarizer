"""Shared test fixtures."""

from unittest.mock import Mock

import pytest

from web_app import TranscriptionState


@pytest.fixture
def transcription_state():
    """Create a fresh TranscriptionState for testing."""
    return TranscriptionState()


@pytest.fixture
def sample_transcript_content():
    """Sample transcript file content for testing."""
    return (
        "Transcript started: 2026-01-15 10:30:00\n"
        "Audio device: BlackHole 2ch\n"
        "Audio file: recording_2026-01-15_10-30-00.wav\n"
        "Model: large-v3-turbo\n"
        "Duration: 5:30\n"
        "\n"
        "[00:01] Hello everyone, welcome to the meeting.\n"
        "[00:15] Today we'll discuss the project roadmap.\n"
        "[01:30] Let's start with the first item on the agenda.\n"
    )


@pytest.fixture
def mock_page():
    """Create a mock Playwright Page for page object tests."""
    page = Mock()
    page.query_selector.return_value = None
    page.wait_for_selector.return_value = None
    page.query_selector_all.return_value = []
    page.content.return_value = ""
    return page
