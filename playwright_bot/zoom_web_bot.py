"""Playwright-based Zoom web client bot for meeting transcription."""

from __future__ import annotations

import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from playwright_bot.audio import AudioCapturer, AudioProcessor
from playwright_bot.exceptions import (
    BreakoutRoomError,
    BreakoutRoomNotFoundError,
    BreakoutRoomsNotAvailableError,
    BrowserLaunchError,
    JoinError,
    NavigationError,
    WaitingRoomTimeoutError,
)
from playwright_bot.meeting_monitor import MeetingEvent, MeetingMonitor, MonitorEvent
from playwright_bot.page_objects.breakout_room_page import BreakoutRoomPage
from playwright_bot.page_objects.meeting_page import MeetingPage
from playwright_bot.page_objects.pre_join_page import PreJoinPage
from playwright_bot.page_objects.waiting_room_page import WaitingRoomPage

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright

# Load environment variables
load_dotenv()

# Configuration from environment
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "transcripts")
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
PLAYWRIGHT_TIMEOUT = int(os.getenv("PLAYWRIGHT_TIMEOUT", "60000"))
PLAYWRIGHT_SLOWMO = int(os.getenv("PLAYWRIGHT_SLOWMO", "0"))
PLAYWRIGHT_DEBUG = os.getenv("PLAYWRIGHT_DEBUG", "false").lower() == "true"
PLAYWRIGHT_SCREENSHOTS = os.getenv("PLAYWRIGHT_SCREENSHOTS", "true").lower() == "true"

# Set up logging
logging.basicConfig(
    level=logging.DEBUG if PLAYWRIGHT_DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class BotState(Enum):
    """Bot lifecycle states."""

    IDLE = "idle"
    LAUNCHING = "launching"
    NAVIGATING = "navigating"
    PRE_JOIN = "pre_join"
    JOINING = "joining"
    WAITING_ROOM = "waiting_room"
    IN_MEETING = "in_meeting"
    WAITING_FOR_BREAKOUT = "waiting_for_breakout"
    JOINING_BREAKOUT = "joining_breakout"
    IN_BREAKOUT_ROOM = "in_breakout_room"
    RECORDING = "recording"
    MEETING_ENDED = "meeting_ended"
    ERROR = "error"
    CLOSING = "closing"


class JoinResult(Enum):
    """Result of the join attempt after pre-join."""

    DIRECT_JOIN = "direct_join"
    WAITING_ROOM = "waiting_room"
    ERROR = "error"


@dataclass
class BotConfig:
    """Configuration for the Zoom web bot."""

    meeting_url: str
    bot_name: str = "Transcription Bot"
    meeting_password: str = ""
    breakout_room: str = ""  # Target breakout room name
    headless: bool = field(default_factory=lambda: PLAYWRIGHT_HEADLESS)
    timeout_ms: int = field(default_factory=lambda: PLAYWRIGHT_TIMEOUT)
    waiting_room_timeout_ms: int = 300000  # 5 minutes for waiting room
    breakout_timeout_ms: int = 300000  # 5 minutes waiting for breakout rooms
    screenshot_on_error: bool = field(default_factory=lambda: PLAYWRIGHT_SCREENSHOTS)
    enable_audio_capture: bool = True
    audio_output_dir: str = field(default_factory=lambda: OUTPUT_DIR)


class ZoomWebBot:
    """Playwright-based Zoom web client bot.

    This bot uses a headless browser to join Zoom meetings via the web client.
    It handles the pre-join flow, waiting room, and meeting detection.

    Usage:
        config = BotConfig(
            meeting_url="https://zoom.us/j/123456789",
            bot_name="My Bot",
        )
        bot = ZoomWebBot(config)

        if bot.start():
            print("Successfully joined meeting!")
            # ... do work ...
            bot.stop()
    """

    def __init__(self, config: BotConfig) -> None:
        """Initialize the Zoom web bot.

        Args:
            config: Bot configuration
        """
        self.config = config
        self._state = BotState.IDLE
        self._error_message: str | None = None

        # Playwright objects (initialized on start)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

        # Page objects (initialized after page creation)
        self._pre_join_page: PreJoinPage | None = None
        self._waiting_room_page: WaitingRoomPage | None = None
        self._meeting_page: MeetingPage | None = None
        self._breakout_room_page: BreakoutRoomPage | None = None

        # Audio capture objects
        self._audio_capturer: AudioCapturer | None = None
        self._audio_processor: AudioProcessor | None = None
        self._recording = False

        # Meeting monitor
        self._meeting_monitor: MeetingMonitor | None = None

        # Ensure output directory exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    @property
    def state(self) -> BotState:
        """Get the current bot state."""
        return self._state

    @property
    def page(self) -> Page | None:
        """Get the Playwright page instance."""
        return self._page

    @property
    def error_message(self) -> str | None:
        """Get the last error message, if any."""
        return self._error_message

    def _update_state(self, new_state: BotState) -> None:
        """Update the bot state.

        Args:
            new_state: The new state to set
        """
        logger.info(f"State: {self._state.value} -> {new_state.value}")
        self._state = new_state

    def start(self) -> bool:
        """Start the bot and join the meeting.

        This executes the full join flow:
        1. Launch browser
        2. Navigate to meeting URL
        3. Handle pre-join screen
        4. Handle waiting room (if applicable)
        5. Verify meeting join

        Returns:
            True if successfully joined the meeting, False otherwise
        """
        try:
            # Setup signal handlers for graceful shutdown
            self._setup_signal_handlers()

            # Launch browser
            self._update_state(BotState.LAUNCHING)
            self._launch_browser()

            # Navigate to meeting
            self._update_state(BotState.NAVIGATING)
            self._navigate_to_meeting()

            # Handle pre-join screen
            self._update_state(BotState.PRE_JOIN)
            self._handle_pre_join()

            # Wait for join result
            self._update_state(BotState.JOINING)
            join_result = self._wait_for_join_result()

            if join_result == JoinResult.WAITING_ROOM:
                self._update_state(BotState.WAITING_ROOM)
                if not self._wait_for_admission():
                    raise WaitingRoomTimeoutError(
                        f"Timed out waiting for host admission after "
                        f"{self.config.waiting_room_timeout_ms / 1000}s"
                    )

            elif join_result == JoinResult.ERROR:
                error_msg = self._get_error_message()
                raise JoinError(error_msg or "Failed to join meeting")

            # Handle audio join and verify we're in the meeting
            self._handle_audio_join()

            if self._verify_in_meeting():
                self._update_state(BotState.IN_MEETING)
                logger.info("Successfully joined meeting")

                # Start background meeting monitor
                self._start_meeting_monitor()

                return True
            else:
                raise JoinError("Failed to verify meeting join")

        except Exception as e:
            self._update_state(BotState.ERROR)
            self._error_message = str(e)
            self._take_error_screenshot()
            logger.error(f"Failed to join meeting: {e}")
            return False

    def stop(self) -> None:
        """Stop the bot and clean up resources."""
        logger.info("Stopping bot...")
        self._update_state(BotState.CLOSING)

        # Stop meeting monitor
        self._stop_meeting_monitor()

        # Stop audio capture if running
        if self._recording:
            result = self.stop_audio_capture()
            if result:
                wav_path, duration = result
                logger.info(f"Final recording: {wav_path} ({duration:.2f}s)")

        try:
            # Try to leave meeting gracefully (only if still in meeting)
            if self._meeting_page and self._state in (BotState.IN_MEETING, BotState.IN_BREAKOUT_ROOM):
                self._meeting_page.leave_meeting()
        except Exception as e:
            logger.warning(f"Error leaving meeting: {e}")

        # Close browser
        self._close_browser()
        self._update_state(BotState.IDLE)
        logger.info("Bot stopped")

    def get_state(self) -> BotState:
        """Get the current bot state.

        Returns:
            Current BotState
        """
        return self._state

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""

        def shutdown_handler(sig: int, frame: object) -> None:
            print("\n\n   Shutting down bot...")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

    def _launch_browser(self) -> None:
        """Launch Chromium browser with appropriate settings."""
        logger.info(f"Launching browser (headless={self.config.headless})")

        try:
            self._playwright = sync_playwright().start()

            # Launch Chromium with anti-detection and compatibility settings
            self._browser = self._playwright.chromium.launch(
                headless=self.config.headless,
                slow_mo=PLAYWRIGHT_SLOWMO,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--window-size=1280,720",
                    # Audio/video related
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    "--autoplay-policy=no-user-gesture-required",
                ],
            )

            # Create context with pre-granted permissions
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                permissions=["microphone", "camera"],
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )

            # Set default timeout
            self._context.set_default_timeout(self.config.timeout_ms)

            # Create page
            self._page = self._context.new_page()

            # Setup console logging for debugging
            if PLAYWRIGHT_DEBUG:
                self._page.on("console", lambda msg: logger.debug(f"[Browser] {msg.text}"))

            # Initialize page objects
            self._pre_join_page = PreJoinPage(self._page, self.config.timeout_ms)
            self._waiting_room_page = WaitingRoomPage(self._page, self.config.timeout_ms)
            self._meeting_page = MeetingPage(self._page, self.config.timeout_ms)
            self._breakout_room_page = BreakoutRoomPage(self._page, self.config.timeout_ms)

            logger.info("Browser launched successfully")

        except Exception as e:
            raise BrowserLaunchError(f"Failed to launch browser: {e}") from e

    def _close_browser(self) -> None:
        """Close the browser and cleanup Playwright resources."""
        try:
            if self._page:
                self._page.close()
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    def _navigate_to_meeting(self) -> None:
        """Navigate to the Zoom meeting URL."""
        if not self._page:
            raise NavigationError("Page not initialized")

        url = self.config.meeting_url
        logger.info(f"Navigating to: {url}")

        # Convert join URL to web client URL if needed
        # https://zoom.us/j/123 -> https://zoom.us/wc/join/123
        if "/j/" in url and "/wc/" not in url:
            url = url.replace("/j/", "/wc/join/")
            logger.debug(f"Converted to web client URL: {url}")

        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
            logger.info("Navigation complete")
        except Exception as e:
            raise NavigationError(f"Failed to navigate to meeting URL: {e}") from e

    def _handle_pre_join(self) -> None:
        """Handle the pre-join screen."""
        if not self._pre_join_page or not self._page:
            raise JoinError("Page objects not initialized")

        logger.info("Handling pre-join screen")

        # Wait for pre-join page to load
        if not self._pre_join_page.is_displayed(timeout_ms=self.config.timeout_ms):
            # Check for error messages
            if self._meeting_page:
                error = self._meeting_page.check_for_error()
                if error:
                    raise JoinError(error)
            raise JoinError("Pre-join screen not displayed")

        # Complete pre-join flow
        self._pre_join_page.complete_pre_join(
            name=self.config.bot_name,
            password=self.config.meeting_password or None,
            disable_video=True,
            disable_audio=False,  # We want audio for transcription
        )

    def _wait_for_join_result(self, timeout_ms: int = 30000) -> JoinResult:
        """Wait and determine the result of the join attempt.

        After clicking join, we either:
        - Go directly to the meeting
        - Enter the waiting room
        - See an error

        Args:
            timeout_ms: Timeout to wait for a result

        Returns:
            JoinResult indicating what happened
        """
        if not self._page or not self._waiting_room_page or not self._meeting_page:
            return JoinResult.ERROR

        import time

        start_time = time.time()
        timeout_seconds = timeout_ms / 1000

        while (time.time() - start_time) < timeout_seconds:
            # Check for errors first
            error = self._meeting_page.check_for_error()
            if error:
                self._error_message = error
                return JoinResult.ERROR

            # Check for waiting room
            if self._waiting_room_page.is_displayed(timeout_ms=1000):
                logger.info("Entered waiting room")
                return JoinResult.WAITING_ROOM

            # Check if we're in the meeting
            if self._meeting_page.is_in_meeting(timeout_ms=1000):
                logger.info("Joined meeting directly")
                return JoinResult.DIRECT_JOIN

            time.sleep(0.5)

        logger.warning("Timed out waiting for join result")
        return JoinResult.ERROR

    def _wait_for_admission(self) -> bool:
        """Wait for admission from the waiting room.

        Returns:
            True if admitted, False if timed out
        """
        if not self._waiting_room_page:
            return False

        return self._waiting_room_page.wait_for_admission(
            timeout_ms=self.config.waiting_room_timeout_ms
        )

    def _handle_audio_join(self) -> None:
        """Handle the audio join dialog if it appears."""
        if self._meeting_page:
            self._meeting_page.handle_audio_join()

    def _verify_in_meeting(self) -> bool:
        """Verify that we're successfully in the meeting.

        Returns:
            True if in meeting
        """
        if not self._meeting_page:
            return False

        return self._meeting_page.wait_for_stable_meeting(timeout_ms=15000)

    def _get_error_message(self) -> str | None:
        """Get any error message from the page.

        Returns:
            Error message or None
        """
        if self._meeting_page:
            return self._meeting_page.check_for_error()
        return self._error_message

    def _take_error_screenshot(self) -> None:
        """Take a screenshot for debugging on error."""
        if not self._page or not self.config.screenshot_on_error:
            return

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path = os.path.join(OUTPUT_DIR, f"error_screenshot_{timestamp}.png")
            self._page.screenshot(path=path)
            logger.info(f"Error screenshot saved: {path}")
        except Exception as e:
            logger.warning(f"Failed to take error screenshot: {e}")

    # -------------------------------------------------------------------------
    # Meeting Monitor Methods
    # -------------------------------------------------------------------------

    def _start_meeting_monitor(self) -> None:
        """Start the background meeting monitor."""
        if not self._meeting_page or not self._breakout_room_page:
            logger.warning("Cannot start monitor - page objects not initialized")
            return

        self._meeting_monitor = MeetingMonitor(
            meeting_page=self._meeting_page,
            breakout_page=self._breakout_room_page,
            poll_interval_ms=2000,
        )
        self._meeting_monitor.set_callback(self._on_meeting_event)
        self._meeting_monitor.start()
        logger.info("Meeting monitor started")

    def _stop_meeting_monitor(self) -> None:
        """Stop the background meeting monitor."""
        if self._meeting_monitor:
            self._meeting_monitor.stop()
            self._meeting_monitor = None
            logger.debug("Meeting monitor stopped")

    def _on_meeting_event(self, event: MonitorEvent) -> None:
        """Handle events from the meeting monitor.

        Args:
            event: The monitor event
        """
        logger.info(f"Meeting event: {event.event_type.value} - {event.detail}")

        if event.event_type == MeetingEvent.MEETING_ENDED:
            self._handle_meeting_ended(event.detail)

        elif event.event_type == MeetingEvent.REMOVED_FROM_MEETING:
            self._handle_meeting_ended(f"Removed from meeting: {event.detail}")

        elif event.event_type == MeetingEvent.RETURNED_TO_MAIN:
            self._handle_returned_to_main()

        elif event.event_type == MeetingEvent.BREAKOUT_CLOSING_SOON:
            logger.warning("Breakout room will close soon")

    def _handle_meeting_ended(self, detail: str | None) -> None:
        """Handle meeting ended or bot removed event.

        Stops audio capture and updates state.

        Args:
            detail: Additional context about why meeting ended
        """
        logger.info(f"Meeting ended: {detail}")

        # Stop audio capture if running
        if self._recording:
            result = self.stop_audio_capture()
            if result:
                wav_path, duration = result
                logger.info(f"Audio saved on meeting end: {wav_path} ({duration:.2f}s)")

        # Update state
        self._update_state(BotState.MEETING_ENDED)
        self._error_message = detail

    def _handle_returned_to_main(self) -> None:
        """Handle being returned to main meeting from breakout room."""
        logger.info("Returned to main meeting from breakout room")

        # Update state if we were in a breakout room
        if self._state == BotState.IN_BREAKOUT_ROOM:
            self._update_state(BotState.IN_MEETING)

            # Update monitor state
            if self._meeting_monitor:
                self._meeting_monitor.set_in_breakout_room(False)

    # -------------------------------------------------------------------------
    # Breakout Room Methods
    # -------------------------------------------------------------------------

    def wait_for_breakout_rooms(self, timeout_ms: int | None = None) -> bool:
        """Wait for breakout rooms to become available.

        Polls for the breakout rooms button to appear in the toolbar.
        The host must open breakout rooms and enable "Allow participants
        to choose room" for this to work.

        Args:
            timeout_ms: Maximum time to wait (default from config)

        Returns:
            True if breakout rooms became available, False if timed out
        """
        if not self._breakout_room_page:
            logger.error("Breakout room page not initialized")
            return False

        if self._state != BotState.IN_MEETING:
            logger.warning(f"Cannot wait for breakout rooms in state: {self._state}")
            return False

        self._update_state(BotState.WAITING_FOR_BREAKOUT)
        timeout = timeout_ms or self.config.breakout_timeout_ms

        try:
            result = self._breakout_room_page.wait_for_breakout_rooms_available(timeout_ms=timeout)
            if not result:
                # Revert state if we timed out
                self._update_state(BotState.IN_MEETING)
            return result
        except Exception as e:
            logger.error(f"Error waiting for breakout rooms: {e}")
            self._update_state(BotState.IN_MEETING)
            return False

    def get_available_breakout_rooms(self) -> list[str]:
        """Get list of available breakout room names.

        Returns:
            List of room names

        Raises:
            BreakoutRoomsNotAvailableError: If breakout rooms not available
        """
        if not self._breakout_room_page:
            raise BreakoutRoomsNotAvailableError("Breakout room page not initialized")

        return self._breakout_room_page.get_available_rooms()

    def join_breakout_room(self, room_name: str) -> bool:
        """Join a specific breakout room by name.

        Args:
            room_name: Name of the room to join (case-insensitive)

        Returns:
            True if successfully joined the breakout room

        Raises:
            BreakoutRoomNotFoundError: If room not found
            BreakoutRoomsNotAvailableError: If breakout rooms not available
            BreakoutRoomError: For other breakout room errors
        """
        if not self._breakout_room_page:
            raise BreakoutRoomsNotAvailableError("Breakout room page not initialized")

        if self._state not in (BotState.IN_MEETING, BotState.WAITING_FOR_BREAKOUT):
            raise BreakoutRoomError(f"Cannot join breakout room in state: {self._state}")

        self._update_state(BotState.JOINING_BREAKOUT)

        try:
            # Attempt to join the room
            if not self._breakout_room_page.join_room_by_name(room_name):
                self._update_state(BotState.IN_MEETING)
                return False

            # Wait for the join to complete
            if self._breakout_room_page.wait_for_room_join(timeout_ms=30000):
                self._update_state(BotState.IN_BREAKOUT_ROOM)
                logger.info(f"Successfully joined breakout room: {room_name}")

                # Update monitor state
                if self._meeting_monitor:
                    self._meeting_monitor.set_in_breakout_room(True)

                return True
            else:
                logger.warning("Join initiated but couldn't verify room entry")
                # Still might have joined, check state
                if self._breakout_room_page.is_in_breakout_room():
                    self._update_state(BotState.IN_BREAKOUT_ROOM)

                    # Update monitor state
                    if self._meeting_monitor:
                        self._meeting_monitor.set_in_breakout_room(True)

                    return True
                self._update_state(BotState.IN_MEETING)
                return False

        except BreakoutRoomNotFoundError:
            self._update_state(BotState.IN_MEETING)
            raise
        except Exception as e:
            logger.error(f"Error joining breakout room: {e}")
            self._update_state(BotState.IN_MEETING)
            self._take_error_screenshot()
            raise BreakoutRoomError(f"Failed to join breakout room: {e}") from e

    def leave_breakout_room(self) -> bool:
        """Leave the current breakout room and return to main meeting.

        Returns:
            True if successfully left breakout room
        """
        if not self._breakout_room_page:
            return False

        if self._state != BotState.IN_BREAKOUT_ROOM:
            logger.warning(f"Not in breakout room (state: {self._state})")
            return False

        try:
            if self._breakout_room_page.leave_breakout_room():
                # Wait briefly for transition
                import time

                time.sleep(2)

                # Verify we're back in main meeting
                if not self._breakout_room_page.is_in_breakout_room():
                    self._update_state(BotState.IN_MEETING)
                    logger.info("Left breakout room, back in main meeting")

                    # Update monitor state
                    if self._meeting_monitor:
                        self._meeting_monitor.set_in_breakout_room(False)

                    return True

            return False
        except Exception as e:
            logger.error(f"Error leaving breakout room: {e}")
            return False

    def is_in_breakout_room(self) -> bool:
        """Check if currently in a breakout room.

        Returns:
            True if in a breakout room
        """
        if not self._breakout_room_page:
            return False
        return self._breakout_room_page.is_in_breakout_room()

    def are_breakout_rooms_available(self) -> bool:
        """Check if breakout rooms are currently available.

        Returns:
            True if breakout rooms button is visible
        """
        if not self._breakout_room_page:
            return False
        return self._breakout_room_page.is_breakout_button_visible()

    # -------------------------------------------------------------------------
    # Audio Capture Methods
    # -------------------------------------------------------------------------

    def _on_audio_data(self, audio_bytes: bytes, sample_rate: int, channels: int) -> None:
        """Callback for receiving audio data from the browser.

        Args:
            audio_bytes: Raw audio bytes (Float32Array from browser)
            sample_rate: Sample rate in Hz
            channels: Number of audio channels
        """
        if self._audio_processor and self._audio_processor.is_processing:
            self._audio_processor.process(audio_bytes, sample_rate, channels)

    def start_audio_capture(self) -> bool:
        """Start capturing audio from the meeting.

        This injects JavaScript into the browser to intercept audio streams
        and convert them to Whisper-compatible format.

        Returns:
            True if audio capture started successfully

        Note:
            Bot must be in IN_MEETING or IN_BREAKOUT_ROOM state.
        """
        if not self.config.enable_audio_capture:
            logger.warning("Audio capture is disabled in config")
            return False

        if self._state not in (BotState.IN_MEETING, BotState.IN_BREAKOUT_ROOM):
            logger.warning(f"Cannot start audio capture in state: {self._state}")
            return False

        if self._recording:
            logger.warning("Audio capture already running")
            return True

        if not self._page:
            logger.error("Page not initialized")
            return False

        try:
            # Initialize audio processor
            self._audio_processor = AudioProcessor(output_dir=self.config.audio_output_dir)
            wav_path = self._audio_processor.start()
            logger.info(f"Audio will be saved to: {wav_path}")

            # Initialize and start audio capturer
            self._audio_capturer = AudioCapturer(
                page=self._page,
                on_audio_data=self._on_audio_data,
            )

            if self._audio_capturer.start():
                self._recording = True
                logger.info("Audio capture started successfully")
                return True
            else:
                # Clean up on failure
                self._audio_processor.stop()
                self._audio_processor = None
                self._audio_capturer = None
                return False

        except Exception as e:
            logger.error(f"Failed to start audio capture: {e}")
            self._take_error_screenshot()

            # Clean up
            if self._audio_processor:
                self._audio_processor.stop()
                self._audio_processor = None
            self._audio_capturer = None
            self._recording = False

            return False

    def stop_audio_capture(self) -> tuple[str, float] | None:
        """Stop capturing audio and return the WAV file path.

        Returns:
            Tuple of (wav_path, duration_seconds) or None if not recording
        """
        if not self._recording:
            return None

        result = None

        try:
            # Stop the capturer first
            if self._audio_capturer:
                self._audio_capturer.stop()
                logger.info(
                    f"Audio capturer stopped. "
                    f"Received {self._audio_capturer.get_duration_seconds():.2f}s of audio"
                )

            # Stop the processor and get file info
            if self._audio_processor:
                result = self._audio_processor.stop()
                if result:
                    wav_path, duration = result
                    logger.info(f"Audio saved: {wav_path} ({duration:.2f}s)")

        except Exception as e:
            logger.error(f"Error stopping audio capture: {e}")
        finally:
            self._audio_capturer = None
            self._audio_processor = None
            self._recording = False

        return result

    def is_recording(self) -> bool:
        """Check if audio recording is currently active.

        Returns:
            True if recording
        """
        return self._recording

    def get_recording_duration(self) -> float:
        """Get the current recording duration in seconds.

        Returns:
            Duration in seconds, or 0 if not recording
        """
        if self._audio_processor and self._audio_processor.is_processing:
            return self._audio_processor.duration
        return 0.0

    def get_recording_path(self) -> str | None:
        """Get the path to the current recording file.

        Returns:
            Path to WAV file or None if not recording
        """
        if self._audio_processor:
            return self._audio_processor.wav_path
        return None


def main() -> None:
    """Main entry point for testing the bot."""
    import argparse

    parser = argparse.ArgumentParser(description="Zoom Web Bot")
    parser.add_argument("meeting_url", help="Zoom meeting URL")
    parser.add_argument("--name", default="Transcription Bot", help="Bot display name")
    parser.add_argument("--password", default="", help="Meeting password")
    parser.add_argument("--headed", action="store_true", help="Run in headed mode")

    args = parser.parse_args()

    print("=" * 60)
    print("   Zoom Web Bot")
    print("=" * 60)
    print(f"\n   Meeting URL: {args.meeting_url}")
    print(f"   Bot Name: {args.name}")
    print(f"   Headless: {not args.headed}")
    print()

    config = BotConfig(
        meeting_url=args.meeting_url,
        bot_name=args.name,
        meeting_password=args.password,
        headless=not args.headed,
    )

    bot = ZoomWebBot(config)

    try:
        if bot.start():
            print("\n   Successfully joined meeting!")
            print(f"   State: {bot.get_state().value}")
            input("\n   Press Enter to leave meeting...")
        else:
            print("\n   Failed to join meeting")
            print(f"   Error: {bot.error_message}")
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
