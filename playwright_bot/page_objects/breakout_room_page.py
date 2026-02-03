"""Page object for Zoom breakout room navigation."""

from __future__ import annotations

import logging
import time

from playwright_bot.exceptions import (
    BreakoutRoomNotFoundError,
    BreakoutRoomsNotAvailableError,
)
from playwright_bot.page_objects.base_page import BasePage
from playwright_bot.selectors import BreakoutRoomSelectors

logger = logging.getLogger(__name__)


class BreakoutRoomPage(BasePage):
    """Handles interactions with Zoom breakout room UI.

    This page object handles:
    - Detecting when breakout rooms become available
    - Opening the room selection panel
    - Listing available rooms
    - Joining a specific room by name
    - Detecting when we're in a breakout room
    - Leaving a breakout room
    """

    def is_breakout_button_visible(self) -> bool:
        """Check if the breakout rooms button is visible in the toolbar.

        The button only appears when the host has opened breakout rooms
        and "Allow participants to choose room" is enabled.

        Returns:
            True if breakout rooms button is visible
        """
        try:
            button = self.page.query_selector(BreakoutRoomSelectors.BREAKOUT_BUTTON)
            if button and button.is_visible():
                logger.debug("Breakout rooms button is visible")
                return True
        except Exception as e:
            logger.debug(f"Error checking breakout button: {e}")
        return False

    def is_room_list_open(self) -> bool:
        """Check if the breakout room list panel is currently open.

        Returns:
            True if room list panel is open
        """
        try:
            room_list = self.page.query_selector(BreakoutRoomSelectors.ROOM_LIST)
            if room_list and room_list.is_visible():
                return True
        except Exception:
            pass
        return False

    def is_in_breakout_room(self) -> bool:
        """Check if we're currently in a breakout room.

        Detects breakout room by looking for:
        - "Leave Room" button (instead of "Leave Meeting")
        - Breakout room indicator in UI

        Returns:
            True if currently in a breakout room
        """
        try:
            # Check for "Leave Room" button which only appears in breakout rooms
            leave_room_button = self.page.query_selector(BreakoutRoomSelectors.LEAVE_ROOM_BUTTON)
            if leave_room_button and leave_room_button.is_visible():
                logger.debug("In breakout room (Leave Room button visible)")
                return True
        except Exception:
            pass

        # Fallback: check page content for breakout room indicators
        try:
            page_text = self.page.content().lower()
            if "breakout room" in page_text and "leave room" in page_text:
                return True
        except Exception:
            pass

        return False

    def open_room_list(self) -> bool:
        """Open the breakout room list panel.

        Returns:
            True if room list was successfully opened

        Raises:
            BreakoutRoomsNotAvailableError: If breakout rooms button not found
        """
        if self.is_room_list_open():
            logger.debug("Room list already open")
            return True

        if not self.is_breakout_button_visible():
            raise BreakoutRoomsNotAvailableError(
                "Breakout rooms button not visible - rooms may not be open"
            )

        try:
            button = self.page.wait_for_selector(
                BreakoutRoomSelectors.BREAKOUT_BUTTON,
                timeout=5000,
                state="visible",
            )
            if button:
                logger.info("Opening breakout room list")
                button.click()

                # Wait for room list to appear
                self.page.wait_for_selector(
                    BreakoutRoomSelectors.ROOM_LIST,
                    timeout=5000,
                    state="visible",
                )
                logger.debug("Room list opened successfully")
                return True
        except Exception as e:
            logger.warning(f"Failed to open room list: {e}")

        return False

    def close_room_list(self) -> None:
        """Close the breakout room list panel if it's open."""
        if not self.is_room_list_open():
            return

        try:
            # Try clicking the breakout button again to toggle it closed
            button = self.page.query_selector(BreakoutRoomSelectors.BREAKOUT_BUTTON)
            if button:
                button.click()
                time.sleep(0.5)
        except Exception as e:
            logger.debug(f"Error closing room list: {e}")

    def get_available_rooms(self) -> list[str]:
        """Get list of available breakout room names.

        Returns:
            List of room names

        Raises:
            BreakoutRoomsNotAvailableError: If unable to get room list
        """
        rooms: list[str] = []

        # Ensure room list is open
        if not self.is_room_list_open():
            self.open_room_list()

        try:
            # Find all room items
            room_elements = self.page.query_selector_all(BreakoutRoomSelectors.ROOM_ITEM)

            if not room_elements:
                # Try alternative: look for room names directly
                name_elements = self.page.query_selector_all(BreakoutRoomSelectors.ROOM_NAME)
                for name_element in name_elements:
                    try:
                        room_name = name_element.inner_text().strip()
                        if room_name and room_name not in rooms:
                            rooms.append(room_name)
                    except Exception:
                        pass
            else:
                for element in room_elements:
                    try:
                        # Try to find name within the room item
                        name_element = element.query_selector(BreakoutRoomSelectors.ROOM_NAME)
                        if name_element:
                            room_name = name_element.inner_text().strip()
                        else:
                            # Fallback: use the element's text directly
                            room_name = element.inner_text().strip()
                            # Clean up - room text might include participant count
                            room_name = room_name.split("\n")[0].strip()

                        if room_name and room_name not in rooms:
                            rooms.append(room_name)
                    except Exception:
                        pass

            logger.info(f"Found {len(rooms)} breakout rooms: {rooms}")
            return rooms

        except Exception as e:
            logger.error(f"Failed to get available rooms: {e}")
            raise BreakoutRoomsNotAvailableError(f"Failed to get breakout room list: {e}") from e

    def join_room_by_name(self, room_name: str) -> bool:
        """Join a specific breakout room by name.

        Args:
            room_name: Name of the room to join (case-insensitive match)

        Returns:
            True if join was initiated successfully

        Raises:
            BreakoutRoomNotFoundError: If room with given name not found
            BreakoutRoomsNotAvailableError: If breakout rooms not available
        """
        logger.info(f"Attempting to join breakout room: '{room_name}'")

        # Ensure room list is open
        if not self.is_room_list_open():
            self.open_room_list()

        # Get available rooms for error reporting
        available_rooms = self.get_available_rooms()

        # Case-insensitive search
        target_room_lower = room_name.lower().strip()
        matching_room = None

        for room in available_rooms:
            if room.lower().strip() == target_room_lower:
                matching_room = room
                break

        if not matching_room:
            raise BreakoutRoomNotFoundError(room_name, available_rooms)

        # Find and click the room
        try:
            room_elements = self.page.query_selector_all(BreakoutRoomSelectors.ROOM_ITEM)

            for element in room_elements:
                try:
                    # Check if this is the right room
                    name_element = element.query_selector(BreakoutRoomSelectors.ROOM_NAME)
                    if name_element:
                        element_room_name = name_element.inner_text().strip()
                    else:
                        element_room_name = element.inner_text().split("\n")[0].strip()

                    if element_room_name.lower().strip() == target_room_lower:
                        # Found the room - try to click join button
                        join_button = element.query_selector(BreakoutRoomSelectors.JOIN_ROOM_BUTTON)

                        if join_button and join_button.is_visible():
                            logger.info(f"Clicking join button for '{matching_room}'")
                            join_button.click()
                            return True
                        else:
                            # Some UIs require clicking the room item itself
                            logger.info(f"Clicking room item for '{matching_room}'")
                            element.click()

                            # Look for join button that might appear after click
                            time.sleep(0.5)
                            join_button = self.page.query_selector(
                                BreakoutRoomSelectors.JOIN_ROOM_BUTTON
                            )
                            if join_button and join_button.is_visible():
                                join_button.click()
                            return True

                except Exception as e:
                    logger.debug(f"Error processing room element: {e}")
                    continue

            # If we get here, we found the room in the list but couldn't click it
            logger.warning(f"Found room '{matching_room}' but couldn't click join")
            return False

        except Exception as e:
            logger.error(f"Error joining room: {e}")
            return False

    def leave_breakout_room(self) -> bool:
        """Leave the current breakout room and return to main meeting.

        Returns:
            True if successfully initiated leave
        """
        if not self.is_in_breakout_room():
            logger.warning("Not currently in a breakout room")
            return False

        try:
            leave_button = self.page.wait_for_selector(
                BreakoutRoomSelectors.LEAVE_ROOM_BUTTON,
                timeout=5000,
                state="visible",
            )
            if leave_button:
                logger.info("Leaving breakout room")
                leave_button.click()

                # Handle confirmation dialog if it appears
                try:
                    confirm_button = self.page.wait_for_selector(
                        'button:has-text("Leave")',
                        timeout=3000,
                        state="visible",
                    )
                    if confirm_button:
                        confirm_button.click()
                except Exception:
                    pass

                return True
        except Exception as e:
            logger.warning(f"Failed to leave breakout room: {e}")

        return False

    def wait_for_breakout_rooms_available(
        self,
        timeout_ms: int = 300000,
        poll_interval_ms: int = 2000,
    ) -> bool:
        """Wait for breakout rooms to become available.

        Polls for the breakout rooms button to appear in the toolbar,
        which indicates the host has opened breakout rooms.

        Args:
            timeout_ms: Maximum time to wait (default 5 minutes)
            poll_interval_ms: How often to check (default 2 seconds)

        Returns:
            True if breakout rooms became available, False if timed out
        """
        logger.info(f"Waiting for breakout rooms (timeout: {timeout_ms / 1000}s)")

        start_time = time.time()
        timeout_seconds = timeout_ms / 1000
        poll_seconds = poll_interval_ms / 1000

        while (time.time() - start_time) < timeout_seconds:
            if self.is_breakout_button_visible():
                logger.info("Breakout rooms are now available!")
                return True

            # Log progress periodically
            elapsed = time.time() - start_time
            if int(elapsed) % 30 == 0 and elapsed > 1:
                logger.info(f"Still waiting for breakout rooms... ({int(elapsed)}s elapsed)")

            time.sleep(poll_seconds)

        logger.warning(f"Timed out waiting for breakout rooms after {timeout_seconds}s")
        return False

    def is_breakout_closing_soon(self) -> bool:
        """Check if breakout room is about to close.

        Detects messages like "Breakout Rooms will close in X seconds".

        Returns:
            True if breakout room closing warning is displayed
        """
        try:
            closing_element = self.page.query_selector(
                BreakoutRoomSelectors.BREAKOUT_CLOSING_SOON
            )
            if closing_element and closing_element.is_visible():
                logger.debug("Breakout room closing soon indicator detected")
                return True
        except Exception:
            pass

        # Fallback: check page content
        try:
            page_text = self.page.content().lower()
            closing_indicators = [
                "closing soon",
                "will close in",
                "returning to main",
                "seconds remaining",
            ]
            for indicator in closing_indicators:
                if indicator in page_text:
                    return True
        except Exception:
            pass

        return False

    def has_returned_to_main_meeting(self) -> bool:
        """Check if we've been returned to main meeting from breakout.

        Detects when breakout rooms close and we're back in the main meeting.
        This is detected by:
        - No longer seeing "Leave Room" button
        - Seeing regular "Leave Meeting" button
        - Breakout room indicator no longer visible

        Returns:
            True if we appear to have been returned to main meeting
        """
        # If we see the "Leave Room" button, we're still in breakout
        try:
            leave_room_button = self.page.query_selector(
                BreakoutRoomSelectors.LEAVE_ROOM_BUTTON
            )
            if leave_room_button and leave_room_button.is_visible():
                return False
        except Exception:
            pass

        # Check if breakout room indicator is gone
        try:
            indicator = self.page.query_selector(
                BreakoutRoomSelectors.IN_BREAKOUT_INDICATOR
            )
            if indicator and indicator.is_visible():
                return False
        except Exception:
            pass

        # Check page content - if "leave room" not present but "leave meeting" is
        try:
            page_text = self.page.content().lower()
            has_leave_room = "leave room" in page_text
            has_leave_meeting = "leave meeting" in page_text or "leave" in page_text

            if not has_leave_room and has_leave_meeting:
                logger.debug("Appears to have returned to main meeting")
                return True
        except Exception:
            pass

        return False

    def wait_for_room_join(self, timeout_ms: int = 30000) -> bool:
        """Wait for successful join to a breakout room.

        After clicking join, waits for the UI to indicate we're
        in the breakout room.

        Args:
            timeout_ms: Maximum time to wait

        Returns:
            True if successfully joined breakout room
        """
        logger.info("Waiting for breakout room join to complete...")

        start_time = time.time()
        timeout_seconds = timeout_ms / 1000

        while (time.time() - start_time) < timeout_seconds:
            if self.is_in_breakout_room():
                logger.info("Successfully joined breakout room!")
                return True

            # Room list should close after joining
            if not self.is_room_list_open():
                # Brief pause then check if we're in the room
                time.sleep(1)
                if self.is_in_breakout_room():
                    logger.info("Successfully joined breakout room!")
                    return True

            time.sleep(0.5)

        logger.warning("Timed out waiting for breakout room join")
        return False
