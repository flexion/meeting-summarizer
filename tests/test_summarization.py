"""Tests for summarization service."""

import pytest

from src.summarization.service import (
    SummarizationService,
    Summary,
)


class MockSummarizationProvider:
    """Mock provider for testing."""

    def summarize(self, text: str) -> Summary:
        """Mock summarization that returns fixed summary."""
        return Summary(
            brief="This is a test summary",
            key_points=["Point 1", "Point 2"],
            action_items=["Action 1"],
        )


def test_summary_initialization() -> None:
    """Test Summary object initialization."""
    summary = Summary(
        brief="Test brief",
        key_points=["Point 1", "Point 2"],
        action_items=["Action 1"],
    )

    assert summary.brief == "Test brief"
    assert len(summary.key_points) == 2
    assert len(summary.action_items) == 1


def test_summary_without_action_items() -> None:
    """Test Summary with no action items."""
    summary = Summary(brief="Test brief", key_points=["Point 1"])

    assert summary.action_items == []


def test_summarization_service_initialization() -> None:
    """Test service initializes with provider."""
    provider = MockSummarizationProvider()
    service = SummarizationService(provider)

    assert service.provider == provider


def test_summarize_transcript(sample_transcript: str) -> None:
    """Test successful transcript summarization."""
    provider = MockSummarizationProvider()
    service = SummarizationService(provider)

    summary = service.summarize_transcript(sample_transcript)

    assert isinstance(summary, Summary)
    assert summary.brief == "This is a test summary"
    assert len(summary.key_points) == 2


def test_summarize_empty_transcript() -> None:
    """Test summarizing empty transcript raises error."""
    provider = MockSummarizationProvider()
    service = SummarizationService(provider)

    with pytest.raises(ValueError, match="Transcript cannot be empty"):
        service.summarize_transcript("")

    with pytest.raises(ValueError, match="Transcript cannot be empty"):
        service.summarize_transcript("   ")
