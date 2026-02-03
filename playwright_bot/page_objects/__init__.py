"""Page objects for Zoom web client automation."""

from playwright_bot.page_objects.base_page import BasePage
from playwright_bot.page_objects.breakout_room_page import BreakoutRoomPage
from playwright_bot.page_objects.meeting_page import MeetingPage, MeetingStatus
from playwright_bot.page_objects.pre_join_page import PreJoinPage
from playwright_bot.page_objects.waiting_room_page import WaitingRoomPage

__all__ = [
    "BasePage",
    "PreJoinPage",
    "WaitingRoomPage",
    "MeetingPage",
    "MeetingStatus",
    "BreakoutRoomPage",
]
