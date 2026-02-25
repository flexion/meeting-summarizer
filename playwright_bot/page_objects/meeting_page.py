"""Page object for the in-meeting Zoom interface."""

from __future__ import annotations

import logging
from enum import Enum

from playwright_bot.page_objects.base_page import BasePage
from playwright_bot.zoom_selectors import ErrorSelectors, MeetingSelectors

logger = logging.getLogger(__name__)


class MeetingStatus(Enum):
    """Status of the Zoom meeting."""

    ACTIVE = "active"
    ENDED = "ended"
    REMOVED = "removed"
    ERROR = "error"


class MeetingPage(BasePage):
    """Handles interactions with the in-meeting Zoom interface.

    This page object handles the main meeting UI after successfully
    joining a Zoom meeting.
    """

    def is_in_meeting(self, timeout_ms: int | None = None) -> bool:
        """Check if we're currently in the meeting.

        Args:
            timeout_ms: Timeout to wait for meeting elements

        Returns:
            True if in meeting
        """
        timeout = timeout_ms or self.timeout_ms
        try:
            # Look for meeting container
            meeting_container = self.page.wait_for_selector(
                MeetingSelectors.MEETING_CONTAINER,
                timeout=timeout,
                state="visible",
            )
            if meeting_container:
                logger.debug("Meeting container found")
                return True
        except Exception:
            pass

        # Fallback: check for toolbar
        try:
            toolbar = self.page.query_selector(MeetingSelectors.TOOLBAR)
            if toolbar and toolbar.is_visible():
                logger.debug("Meeting toolbar found")
                return True
        except Exception:
            pass

        return False

    def handle_audio_join(self) -> bool:
        """Handle the "Join Audio by Computer" dialog.

        This dialog often appears after joining a meeting, asking how
        the user wants to connect to audio.

        Returns:
            True if dialog was found and handled, False otherwise
        """
        try:
            join_audio_button = self.page.wait_for_selector(
                MeetingSelectors.JOIN_AUDIO_BUTTON,
                timeout=5000,
                state="visible",
            )
            if join_audio_button:
                logger.info("Clicking 'Join Audio by Computer'")
                join_audio_button.click()
                return True
        except Exception:
            logger.debug("No 'Join Audio' dialog found")
        return False

    def is_audio_connected(self) -> bool:
        """Check if audio is connected to the meeting.

        Returns:
            True if audio appears to be connected
        """
        try:
            audio_button = self.page.query_selector(MeetingSelectors.AUDIO_BUTTON)
            if audio_button:
                aria_label = audio_button.get_attribute("aria-label") or ""
                # If we see "mute" or "unmute" in the label, audio is connected
                if "mute" in aria_label.lower():
                    return True
        except Exception:
            pass
        return False

    def get_participant_count(self) -> int | None:
        """Get the current participant count from the meeting UI.

        Returns:
            Number of participants, or None if not available
        """
        try:
            count_element = self.page.query_selector(MeetingSelectors.PARTICIPANT_COUNT)
            if count_element:
                text = count_element.inner_text()
                # Extract number from text (e.g., "3" or "Participants (3)")
                import re

                match = re.search(r"(\d+)", text)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        return None

    def leave_meeting(self) -> bool:
        """Leave the current meeting.

        Returns:
            True if successfully initiated leave, False otherwise
        """
        try:
            leave_button = self.page.wait_for_selector(
                MeetingSelectors.LEAVE_BUTTON,
                timeout=5000,
                state="visible",
            )
            if leave_button:
                logger.info("Clicking leave button")
                leave_button.click()

                # Handle confirmation dialog if it appears
                try:
                    confirm_button = self.page.wait_for_selector(
                        'button:has-text("Leave Meeting")',
                        timeout=3000,
                        state="visible",
                    )
                    if confirm_button:
                        confirm_button.click()
                except Exception:
                    pass

                return True
        except Exception:
            logger.warning("Could not find leave button")
        return False

    def check_for_error(self) -> str | None:
        """Check if there's an error message displayed.

        Returns:
            Error message if found, None otherwise
        """
        error_checks = [
            (ErrorSelectors.MEETING_ENDED, "Meeting has ended"),
            (ErrorSelectors.INVALID_MEETING, "Invalid meeting ID"),
            (ErrorSelectors.NOT_STARTED, "Meeting has not started"),
            (ErrorSelectors.REMOVED, "Removed from meeting"),
        ]

        for selector, error_type in error_checks:
            try:
                error_element = self.page.query_selector(selector)
                if error_element and error_element.is_visible():
                    text = error_element.inner_text()
                    logger.warning(f"Error detected: {error_type} - {text}")
                    return f"{error_type}: {text}"
            except Exception:
                pass

        # Check generic error container
        try:
            error_container = self.page.query_selector(ErrorSelectors.ERROR_CONTAINER)
            if error_container and error_container.is_visible():
                text = error_container.inner_text()
                if text and len(text) > 5:
                    # Filter out known non-error UI notifications
                    non_error_phrases = [
                        "video now started",
                        "video started",
                        "video now stopped",
                        "video stopped",
                        "audio muted",
                        "muted",
                        "unmuted",
                        "start video",
                        "stop video",
                        "recording",
                        "you are muted",
                        # Host/participant notifications
                        "is the host now",
                        "has joined",
                        "has left",
                        "is sharing",
                        "stopped sharing",
                        # Feature notifications
                        "floating reactions",
                        "reactions have",
                        "new animation",
                        "one place for all",
                        "meeting chats",
                        "breakout room",
                        "waiting room",
                        # Settings/tips
                        "better meeting experience",
                        "hardware acceleration",
                        "learn more",
                        "enable the option",
                        # Generic UI
                        "ok",
                        "got it",
                        "dismiss",
                        "close",
                        "new",
                    ]
                    text_lower = text.lower()
                    if not any(phrase in text_lower for phrase in non_error_phrases):
                        logger.warning(f"Error detected: {text}")
                        return text
        except Exception:
            pass

        return None

    def is_meeting_active(self) -> bool:
        """Check if meeting is still active (not ended).

        Returns:
            True if meeting is still active
        """
        status, _ = self.get_meeting_status()
        return status == MeetingStatus.ACTIVE

    def get_meeting_status(self) -> tuple[MeetingStatus, str | None]:
        """Get current meeting status.

        Returns:
            Tuple of (status, detail) where:
            - status is a MeetingStatus enum value
            - detail is additional context (e.g., error message)
        """
        # Check for host ended meeting
        try:
            ended_element = self.page.query_selector(ErrorSelectors.HOST_ENDED_MEETING)
            if ended_element and ended_element.is_visible():
                text = ended_element.inner_text()
                return (MeetingStatus.ENDED, f"Host ended meeting: {text}")
        except Exception:
            pass

        # Check general meeting ended
        try:
            ended_element = self.page.query_selector(ErrorSelectors.MEETING_ENDED)
            if ended_element and ended_element.is_visible():
                text = ended_element.inner_text()
                return (MeetingStatus.ENDED, text)
        except Exception:
            pass

        # Check if removed
        try:
            removed_element = self.page.query_selector(ErrorSelectors.REMOVED)
            if removed_element and removed_element.is_visible():
                text = removed_element.inner_text()
                return (MeetingStatus.REMOVED, text)
        except Exception:
            pass

        # Check other errors
        error = self.check_for_error()
        if error:
            return (MeetingStatus.ERROR, error)

        # Check if meeting UI is still present
        try:
            container = self.page.query_selector(MeetingSelectors.MEETING_CONTAINER)
            if container and container.is_visible():
                return (MeetingStatus.ACTIVE, None)

            toolbar = self.page.query_selector(MeetingSelectors.TOOLBAR)
            if toolbar and toolbar.is_visible():
                return (MeetingStatus.ACTIVE, None)
        except Exception:
            pass

        return (MeetingStatus.ERROR, "Meeting state unknown")

    def wait_for_stable_meeting(self, timeout_ms: int = 10000) -> bool:
        """Wait for the meeting UI to stabilize after joining.

        This helps ensure all meeting elements are loaded before
        proceeding with other operations.

        Args:
            timeout_ms: Maximum time to wait for stabilization

        Returns:
            True if meeting stabilized, False if timed out
        """
        import time

        start_time = time.time()
        timeout_seconds = timeout_ms / 1000

        while (time.time() - start_time) < timeout_seconds:
            # Check if we're in meeting first (prioritize positive detection)
            if self.is_in_meeting(timeout_ms=2000):
                # Brief pause to let UI settle
                time.sleep(1)

                # Verify still in meeting after pause
                if self.is_in_meeting(timeout_ms=2000):
                    logger.info("Meeting UI stabilized")
                    return True

            # Only check for critical errors if not in meeting
            # (notifications can appear while in meeting and shouldn't fail us)
            status, detail = self.get_meeting_status()
            if status in (MeetingStatus.ENDED, MeetingStatus.REMOVED):
                logger.warning(f"Meeting ended/removed: {detail}")
                return False

            time.sleep(0.5)

        logger.warning("Meeting UI did not stabilize in time")
        return False
