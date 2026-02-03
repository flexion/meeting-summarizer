"""Background monitor for meeting status changes."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from playwright_bot.page_objects.meeting_page import MeetingStatus

if TYPE_CHECKING:
    from playwright_bot.page_objects.breakout_room_page import BreakoutRoomPage
    from playwright_bot.page_objects.meeting_page import MeetingPage

logger = logging.getLogger(__name__)


class MeetingEvent(Enum):
    """Events that can be detected by the meeting monitor."""

    MEETING_ENDED = "meeting_ended"
    REMOVED_FROM_MEETING = "removed_from_meeting"
    BREAKOUT_CLOSING_SOON = "breakout_closing_soon"
    RETURNED_TO_MAIN = "returned_to_main"


@dataclass
class MonitorEvent:
    """Event data from the meeting monitor."""

    event_type: MeetingEvent
    detail: str | None = None


class MeetingMonitor:
    """Background monitor for meeting status changes.

    Uses polling to detect when:
    - Host ends the meeting
    - Bot is removed/kicked from meeting
    - Breakout rooms are closing soon
    - Bot has been returned to main meeting from breakout

    Usage:
        monitor = MeetingMonitor(meeting_page, breakout_page)
        monitor.set_callback(my_callback)
        monitor.start()
        # ... later ...
        monitor.stop()
    """

    def __init__(
        self,
        meeting_page: MeetingPage,
        breakout_page: BreakoutRoomPage,
        poll_interval_ms: int = 2000,
    ) -> None:
        """Initialize the meeting monitor.

        Args:
            meeting_page: MeetingPage instance for status checks
            breakout_page: BreakoutRoomPage instance for breakout checks
            poll_interval_ms: Polling interval in milliseconds (default 2s)
        """
        self._meeting_page = meeting_page
        self._breakout_page = breakout_page
        self._poll_interval_ms = poll_interval_ms

        self._callback: Callable[[MonitorEvent], None] | None = None
        self._in_breakout_room = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Track if we've already fired certain one-time events
        self._closing_soon_fired = False

    def set_callback(self, callback: Callable[[MonitorEvent], None]) -> None:
        """Set the callback function for events.

        Args:
            callback: Function to call when events are detected
        """
        self._callback = callback

    def set_in_breakout_room(self, in_breakout: bool) -> None:
        """Update the monitor's breakout room state.

        Args:
            in_breakout: True if currently in a breakout room
        """
        with self._lock:
            was_in_breakout = self._in_breakout_room
            self._in_breakout_room = in_breakout

            # Reset closing soon flag when entering a new breakout room
            if in_breakout and not was_in_breakout:
                self._closing_soon_fired = False

            logger.debug(f"Monitor breakout state: {in_breakout}")

    def start(self) -> None:
        """Start the background monitoring thread."""
        if self._running:
            logger.warning("Monitor already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"Meeting monitor started (poll interval: {self._poll_interval_ms}ms)")

    def stop(self) -> None:
        """Stop the background monitoring thread."""
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Meeting monitor stopped")

    def is_running(self) -> bool:
        """Check if the monitor is currently running.

        Returns:
            True if monitoring thread is active
        """
        return self._running

    def _monitor_loop(self) -> None:
        """Main monitoring loop that runs in background thread."""
        poll_seconds = self._poll_interval_ms / 1000

        while self._running:
            try:
                self._check_status()
            except Exception as e:
                # Log but don't crash the monitor on errors
                logger.debug(f"Monitor check error (non-fatal): {e}")

            time.sleep(poll_seconds)

    def _check_status(self) -> None:
        """Check meeting status and fire events if needed."""
        with self._lock:
            in_breakout = self._in_breakout_room

        # Check if meeting is still active
        status, detail = self._meeting_page.get_meeting_status()

        if status == MeetingStatus.ENDED:
            logger.info(f"Meeting ended detected: {detail}")
            self._fire_event(MeetingEvent.MEETING_ENDED, detail)
            self.stop()  # Stop monitoring after meeting ends
            return

        if status == MeetingStatus.REMOVED:
            logger.info(f"Removed from meeting detected: {detail}")
            self._fire_event(MeetingEvent.REMOVED_FROM_MEETING, detail)
            self.stop()  # Stop monitoring after removal
            return

        # If in breakout room, check for breakout-specific events
        if in_breakout:
            # Check for breakout room closing soon
            if not self._closing_soon_fired and self._breakout_page.is_breakout_closing_soon():
                logger.info("Breakout room closing soon")
                self._closing_soon_fired = True
                self._fire_event(MeetingEvent.BREAKOUT_CLOSING_SOON, None)

            # Check if returned to main meeting
            if self._breakout_page.has_returned_to_main_meeting():
                # Double-check we're not in breakout
                if not self._breakout_page.is_in_breakout_room():
                    logger.info("Returned to main meeting from breakout")
                    self._fire_event(MeetingEvent.RETURNED_TO_MAIN, None)
                    with self._lock:
                        self._in_breakout_room = False

    def _fire_event(self, event_type: MeetingEvent, detail: str | None) -> None:
        """Fire an event to the callback.

        Args:
            event_type: Type of event
            detail: Optional detail string
        """
        if self._callback:
            try:
                event = MonitorEvent(event_type=event_type, detail=detail)
                self._callback(event)
            except Exception as e:
                logger.error(f"Error in event callback: {e}")
