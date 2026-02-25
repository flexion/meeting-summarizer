"""Tests for playwright_bot/exceptions.py."""

from playwright_bot.exceptions import (
    BreakoutRoomError,
    BreakoutRoomNotFoundError,
    BrowserLaunchError,
    InvalidMeetingError,
    JoinError,
    JoinTimeoutError,
    MeetingEndedError,
    NavigationError,
    SelectorNotFoundError,
    WaitingRoomTimeoutError,
    ZoomBotError,
)


class TestSelectorNotFoundError:
    """Tests for SelectorNotFoundError."""

    def test_message_without_context(self):
        err = SelectorNotFoundError("#my-button")
        assert str(err) == "Selector not found: #my-button"
        assert err.selector == "#my-button"
        assert err.context == ""

    def test_message_with_context(self):
        err = SelectorNotFoundError(".join-btn", context="pre-join page")
        assert str(err) == "Selector not found: .join-btn (context: pre-join page)"
        assert err.selector == ".join-btn"
        assert err.context == "pre-join page"


class TestBreakoutRoomNotFoundError:
    """Tests for BreakoutRoomNotFoundError."""

    def test_message_without_available_rooms(self):
        err = BreakoutRoomNotFoundError("Room 5")
        assert "Room 5" in str(err)
        assert err.room_name == "Room 5"
        assert err.available_rooms == []

    def test_message_with_available_rooms(self):
        rooms = ["Room 1", "Room 2", "Room 3"]
        err = BreakoutRoomNotFoundError("Room 5", available_rooms=rooms)
        msg = str(err)
        assert "Room 5" in msg
        assert "Room 1" in msg
        assert "Room 2" in msg
        assert "Room 3" in msg
        assert err.available_rooms == rooms


class TestExceptionHierarchy:
    """Tests for exception inheritance."""

    def test_all_inherit_from_zoom_bot_error(self):
        assert issubclass(BrowserLaunchError, ZoomBotError)
        assert issubclass(NavigationError, ZoomBotError)
        assert issubclass(JoinError, ZoomBotError)
        assert issubclass(SelectorNotFoundError, ZoomBotError)
        assert issubclass(BreakoutRoomError, ZoomBotError)

    def test_join_error_subtypes(self):
        assert issubclass(JoinTimeoutError, JoinError)
        assert issubclass(WaitingRoomTimeoutError, JoinError)
        assert issubclass(MeetingEndedError, JoinError)
        assert issubclass(InvalidMeetingError, JoinError)

    def test_breakout_room_subtypes(self):
        assert issubclass(BreakoutRoomNotFoundError, BreakoutRoomError)

    def test_catch_zoom_bot_error_catches_subtypes(self):
        with __import__("pytest").raises(ZoomBotError):
            raise BrowserLaunchError("test")

        with __import__("pytest").raises(ZoomBotError):
            raise SelectorNotFoundError("#btn")

        with __import__("pytest").raises(ZoomBotError):
            raise BreakoutRoomNotFoundError("Room 1")

    def test_zoom_bot_error_inherits_from_exception(self):
        assert issubclass(ZoomBotError, Exception)
