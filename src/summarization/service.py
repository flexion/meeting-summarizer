"""AI-powered summarization service."""

from typing import Protocol


class Summary:
    """Structured summary result."""

    def __init__(
        self,
        brief: str,
        key_points: list[str],
        action_items: list[str] | None = None,
    ) -> None:
        """Initialize summary.

        Args:
            brief: Brief summary paragraph.
            key_points: List of key discussion points.
            action_items: Optional list of action items identified.
        """
        self.brief = brief
        self.key_points = key_points
        self.action_items = action_items or []


class SummarizationProvider(Protocol):
    """Protocol for AI summarization providers."""

    def summarize(self, text: str) -> Summary:
        """Generate a summary from text.

        Args:
            text: Input text to summarize.

        Returns:
            Structured summary.
        """
        ...


class SummarizationService:
    """Service for generating meeting summaries."""

    def __init__(self, provider: SummarizationProvider) -> None:
        """Initialize summarization service.

        Args:
            provider: AI provider for summarization.
        """
        self.provider = provider

    def summarize_transcript(self, transcript: str) -> Summary:
        """Generate a summary from a meeting transcript.

        Args:
            transcript: Full meeting transcript text.

        Returns:
            Structured summary with key points and action items.

        Raises:
            ValueError: If transcript is empty.
        """
        if not transcript or not transcript.strip():
            raise ValueError("Transcript cannot be empty")

        return self.provider.summarize(transcript)
