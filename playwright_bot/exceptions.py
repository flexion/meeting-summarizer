"""Custom exceptions for the Playwright Zoom bot."""


class ZoomBotError(Exception):
    """Base exception for Zoom bot errors."""

    pass


class BrowserLaunchError(ZoomBotError):
    """Failed to launch browser."""

    pass


class NavigationError(ZoomBotError):
    """Failed to navigate to meeting URL."""

    pass


class JoinError(ZoomBotError):
    """Failed to join meeting."""

    pass


class JoinTimeoutError(JoinError):
    """Timed out while joining meeting."""

    pass


class WaitingRoomTimeoutError(JoinError):
    """Timed out waiting in waiting room for host admission."""

    pass


class MeetingEndedError(JoinError):
    """Meeting has ended or is not available."""

    pass


class InvalidMeetingError(JoinError):
    """Meeting ID is invalid or meeting does not exist."""

    pass


class SelectorNotFoundError(ZoomBotError):
    """Expected element not found on page."""

    def __init__(self, selector: str, context: str = "") -> None:
        self.selector = selector
        self.context = context
        message = f"Selector not found: {selector}"
        if context:
            message += f" (context: {context})"
        super().__init__(message)


class BreakoutRoomError(ZoomBotError):
    """Error related to breakout room operations."""

    pass


class BreakoutRoomNotFoundError(BreakoutRoomError):
    """Specified breakout room not found in the list."""

    def __init__(self, room_name: str, available_rooms: list[str] | None = None) -> None:
        self.room_name = room_name
        self.available_rooms = available_rooms or []
        message = f"Breakout room not found: '{room_name}'"
        if self.available_rooms:
            message += f". Available rooms: {', '.join(self.available_rooms)}"
        super().__init__(message)


class BreakoutRoomsNotAvailableError(BreakoutRoomError):
    """Breakout rooms are not available (not opened by host)."""

    pass
