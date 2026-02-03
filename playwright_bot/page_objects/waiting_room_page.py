"""Page object for Zoom waiting room."""

from __future__ import annotations

import logging
import time

from playwright_bot.page_objects.base_page import BasePage
from playwright_bot.zoom_selectors import MeetingSelectors, WaitingRoomSelectors

logger = logging.getLogger(__name__)


class WaitingRoomPage(BasePage):
    """Handles interactions with the Zoom waiting room.

    The waiting room is shown when the host has enabled it and the
    participant must wait to be admitted to the meeting.
    """

    def is_displayed(self, timeout_ms: int | None = None) -> bool:
        """Check if the waiting room is currently displayed.

        Args:
            timeout_ms: Timeout to wait for the waiting room to appear

        Returns:
            True if waiting room is visible
        """
        timeout = timeout_ms or 5000  # Short timeout for detection
        try:
            # Try to find waiting room container
            waiting_container = self.page.wait_for_selector(
                WaitingRoomSelectors.WAITING_CONTAINER,
                timeout=timeout,
                state="visible",
            )
            if waiting_container:
                return True
        except Exception:
            pass

        # Fallback: Check for waiting room text indicators
        try:
            page_text = self.page.content()
            for indicator in WaitingRoomSelectors.WAITING_TEXT_INDICATORS:
                if indicator.lower() in page_text.lower():
                    logger.debug(f"Waiting room detected via text: '{indicator}'")
                    return True
        except Exception:
            pass

        return False

    def get_waiting_message(self) -> str:
        """Get the waiting room message displayed to the user.

        Returns:
            The waiting message text, or empty string if not found
        """
        try:
            message_element = self.page.query_selector(WaitingRoomSelectors.WAITING_MESSAGE)
            if message_element:
                return message_element.inner_text()
        except Exception:
            pass
        return ""

    def wait_for_admission(
        self,
        timeout_ms: int = 300000,
        poll_interval_ms: int = 2000,
    ) -> bool:
        """Wait for the host to admit us from the waiting room.

        This polls the page to detect when we've been admitted (waiting room
        disappears and meeting interface appears).

        Args:
            timeout_ms: Maximum time to wait for admission (default 5 minutes)
            poll_interval_ms: How often to check for admission (default 2 seconds)

        Returns:
            True if admitted to meeting, False if timed out
        """
        logger.info(f"Waiting for host admission (timeout: {timeout_ms / 1000}s)")

        start_time = time.time()
        timeout_seconds = timeout_ms / 1000
        poll_seconds = poll_interval_ms / 1000

        while (time.time() - start_time) < timeout_seconds:
            # Check if we've been admitted (meeting container appears)
            try:
                meeting_container = self.page.query_selector(MeetingSelectors.MEETING_CONTAINER)
                if meeting_container and meeting_container.is_visible():
                    logger.info("Admitted to meeting!")
                    return True
            except Exception:
                pass

            # Check if still in waiting room
            if not self._still_in_waiting_room():
                # Not in waiting room anymore, might be in meeting
                logger.debug("Left waiting room, checking for meeting...")
                time.sleep(1)  # Brief pause for UI transition

                # Double-check we're in the meeting
                try:
                    meeting_container = self.page.query_selector(MeetingSelectors.MEETING_CONTAINER)
                    if meeting_container:
                        logger.info("Admitted to meeting!")
                        return True
                except Exception:
                    pass

            # Log progress periodically
            elapsed = time.time() - start_time
            if int(elapsed) % 30 == 0 and elapsed > 1:
                logger.info(f"Still waiting for admission... ({int(elapsed)}s elapsed)")

            time.sleep(poll_seconds)

        logger.warning(f"Timed out waiting for admission after {timeout_seconds}s")
        return False

    def _still_in_waiting_room(self) -> bool:
        """Check if we're still in the waiting room.

        Returns:
            True if still in waiting room
        """
        try:
            # Check for waiting room container
            waiting_container = self.page.query_selector(WaitingRoomSelectors.WAITING_CONTAINER)
            if waiting_container and waiting_container.is_visible():
                return True

            # Check page text for waiting indicators
            page_text = self.page.content()
            for indicator in WaitingRoomSelectors.WAITING_TEXT_INDICATORS:
                if indicator.lower() in page_text.lower():
                    return True
        except Exception:
            pass

        return False

    def leave_waiting_room(self) -> bool:
        """Leave the waiting room and exit the meeting attempt.

        Returns:
            True if successfully clicked leave, False otherwise
        """
        try:
            leave_button = self.page.wait_for_selector(
                WaitingRoomSelectors.LEAVE_BUTTON,
                timeout=5000,
                state="visible",
            )
            if leave_button:
                logger.info("Leaving waiting room")
                leave_button.click()
                return True
        except Exception:
            logger.warning("Could not find leave button in waiting room")
        return False
