"""Audio-specific exceptions for the Playwright Zoom bot."""

from playwright_bot.exceptions import ZoomBotError


class AudioCaptureError(ZoomBotError):
    """Error during audio capture from browser."""

    pass


class AudioProcessingError(ZoomBotError):
    """Error during audio format conversion or processing."""

    pass
