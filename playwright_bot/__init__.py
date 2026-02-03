"""Playwright-based Zoom web client bot for breakout room transcription."""

from playwright_bot.page_objects.breakout_room_page import BreakoutRoomPage
from playwright_bot.zoom_web_bot import BotConfig, BotState, ZoomWebBot

__all__ = ["ZoomWebBot", "BotConfig", "BotState", "BreakoutRoomPage"]
