"""Page object for Zoom pre-join/lobby screen."""

from __future__ import annotations

import logging

from playwright_bot.page_objects.base_page import BasePage
from playwright_bot.selectors import PreJoinSelectors

logger = logging.getLogger(__name__)


class PreJoinPage(BasePage):
    """Handles interactions with the Zoom pre-join screen.

    This is the first screen shown when joining a meeting via web client,
    where the user enters their name and configures audio/video settings.
    """

    def is_displayed(self, timeout_ms: int | None = None) -> bool:
        """Check if the pre-join screen is currently displayed.

        Args:
            timeout_ms: Timeout to wait for the page to appear

        Returns:
            True if pre-join screen is visible
        """
        timeout = timeout_ms or self.timeout_ms
        try:
            self.page.wait_for_selector(
                PreJoinSelectors.PRE_JOIN_CONTAINER,
                timeout=timeout,
                state="visible",
            )
            # Also check for the name input as a secondary confirmation
            name_input = self.page.query_selector(PreJoinSelectors.NAME_INPUT)
            return name_input is not None
        except Exception:
            return False

    def enter_name(self, name: str) -> None:
        """Enter the display name in the name input field.

        Args:
            name: Display name for the bot in the meeting
        """
        logger.info(f"Entering name: {name}")
        name_input = self.page.wait_for_selector(
            PreJoinSelectors.NAME_INPUT,
            timeout=self.timeout_ms,
            state="visible",
        )
        if name_input:
            # Clear existing text and enter new name
            name_input.click()
            name_input.fill("")
            name_input.fill(name)
            logger.debug("Name entered successfully")

    def enter_password(self, password: str) -> bool:
        """Enter meeting password if the field is present.

        Args:
            password: Meeting password/passcode

        Returns:
            True if password was entered, False if no password field found
        """
        try:
            password_input = self.page.wait_for_selector(
                PreJoinSelectors.PASSWORD_INPUT,
                timeout=5000,
                state="visible",
            )
            if password_input:
                logger.info("Password field detected, entering password")
                password_input.fill(password)
                return True
        except Exception:
            logger.debug("No password field found")
        return False

    def disable_audio(self) -> None:
        """Disable audio (mute) before joining if possible.

        Note: The pre-join screen may not always have this option,
        depending on meeting settings.
        """
        try:
            audio_toggle = self.page.wait_for_selector(
                PreJoinSelectors.AUDIO_MUTE,
                timeout=3000,
                state="visible",
            )
            if audio_toggle:
                # Check current state and toggle if needed
                # Audio button typically has aria-label indicating current state
                aria_label = audio_toggle.get_attribute("aria-label") or ""
                if "unmute" not in aria_label.lower():
                    audio_toggle.click()
                    logger.debug("Audio muted")
        except Exception:
            logger.debug("Audio toggle not found on pre-join screen")

    def disable_video(self) -> None:
        """Disable video (camera off) before joining.

        This is important to reduce bandwidth and avoid showing
        a camera feed from the bot.
        """
        try:
            video_toggle = self.page.wait_for_selector(
                PreJoinSelectors.VIDEO_OFF,
                timeout=3000,
                state="visible",
            )
            if video_toggle:
                # Check current state and toggle if needed
                aria_label = video_toggle.get_attribute("aria-label") or ""
                # If label says "start video" it means video is off, which is what we want
                if "start" not in aria_label.lower() and "off" not in aria_label.lower():
                    video_toggle.click()
                    logger.debug("Video disabled")
        except Exception:
            logger.debug("Video toggle not found on pre-join screen")

    def click_join(self) -> None:
        """Click the join button to enter the meeting."""
        logger.info("Clicking join button")
        join_button = self.page.wait_for_selector(
            PreJoinSelectors.JOIN_BUTTON,
            timeout=self.timeout_ms,
            state="visible",
        )
        if join_button:
            join_button.click()
            logger.debug("Join button clicked")

    def handle_agree_dialog(self) -> bool:
        """Handle terms/agreement dialog if it appears.

        Returns:
            True if dialog was found and handled, False otherwise
        """
        try:
            agree_button = self.page.wait_for_selector(
                PreJoinSelectors.AGREE_BUTTON,
                timeout=3000,
                state="visible",
            )
            if agree_button:
                logger.info("Agreement dialog detected, clicking agree")
                agree_button.click()
                return True
        except Exception:
            logger.debug("No agreement dialog found")
        return False

    def complete_pre_join(
        self,
        name: str,
        password: str | None = None,
        disable_video: bool = True,
        disable_audio: bool = False,
    ) -> None:
        """Complete the entire pre-join flow.

        Args:
            name: Display name for the bot
            password: Meeting password if required
            disable_video: Whether to turn off camera
            disable_audio: Whether to mute audio
        """
        logger.info("Starting pre-join flow")

        # Enter name
        self.enter_name(name)

        # Enter password if provided and field exists
        if password:
            self.enter_password(password)

        # Configure audio/video
        if disable_video:
            self.disable_video()
        if disable_audio:
            self.disable_audio()

        # Handle any agreement dialogs
        self.handle_agree_dialog()

        # Click join
        self.click_join()

        logger.info("Pre-join flow completed")
