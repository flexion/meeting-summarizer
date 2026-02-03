#!/usr/bin/env python3
"""Test script for Zoom breakout room navigation.

Usage:
    python playwright_bot/test_breakout.py "https://zoom.us/j/123" --room "Room 1"
    python playwright_bot/test_breakout.py "https://zoom.us/j/123" --room "Room 1" --headed

This script tests the full breakout room flow:
1. Join meeting
2. Wait for breakout rooms to become available
3. List available rooms
4. Join specified room by name
5. Verify in breakout room
6. Optionally leave and return to main meeting
"""

from __future__ import annotations

import argparse
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

from playwright_bot.exceptions import (
    BreakoutRoomNotFoundError,
    BreakoutRoomsNotAvailableError,
)
from playwright_bot.zoom_web_bot import BotConfig, ZoomWebBot


def print_header() -> None:
    """Print the test header."""
    print()
    print("=" * 60)
    print("   Playwright Zoom Bot - Breakout Room Test")
    print("=" * 60)
    print()


def print_status(label: str, value: str, indent: int = 3) -> None:
    """Print a status line."""
    spaces = " " * indent
    print(f"{spaces}{label}: {value}")


def test_breakout(
    meeting_url: str,
    room_name: str,
    bot_name: str = "Breakout Test Bot",
    password: str = "",
    headless: bool = False,
    wait_timeout: int = 300,
    auto_leave: bool = False,
) -> bool:
    """Test the full breakout room join flow.

    Args:
        meeting_url: Zoom meeting URL
        room_name: Target breakout room name
        bot_name: Display name for the bot
        password: Meeting password (optional)
        headless: Run in headless mode
        wait_timeout: Seconds to wait for breakout rooms
        auto_leave: Automatically leave breakout room after joining

    Returns:
        True if all tests passed
    """
    print_header()

    print_status("Meeting URL", meeting_url)
    print_status("Target Room", room_name)
    print_status("Bot Name", bot_name)
    print_status("Password", "***" if password else "(none)")
    print_status("Headless", str(headless))
    print_status("Wait Timeout", f"{wait_timeout}s")
    print()

    config = BotConfig(
        meeting_url=meeting_url,
        bot_name=bot_name,
        meeting_password=password,
        breakout_room=room_name,
        headless=headless,
        breakout_timeout_ms=wait_timeout * 1000,
        screenshot_on_error=True,
    )

    bot = ZoomWebBot(config)

    try:
        # Step 1: Join meeting
        print("   [1/5] Joining meeting...")
        if not bot.start():
            print("\n   FAILED: Could not join meeting")
            print(f"   Error: {bot.error_message}")
            return False

        print(f"         State: {bot.get_state().value}")
        print("         Meeting joined successfully!")
        print()

        # Step 2: Wait for breakout rooms
        print("   [2/5] Waiting for breakout rooms to open...")
        print("         (Host must open breakout rooms with 'Allow participants to choose room')")
        print()

        if bot.are_breakout_rooms_available():
            print("         Breakout rooms already available!")
        else:
            if not bot.wait_for_breakout_rooms():
                print(f"\n   FAILED: Breakout rooms not available after {wait_timeout}s")
                print("   Make sure the host has:")
                print("   1. Opened breakout rooms")
                print("   2. Enabled 'Allow participants to choose room'")
                return False

        print(f"         State: {bot.get_state().value}")
        print("         Breakout rooms are available!")
        print()

        # Step 3: List available rooms
        print("   [3/5] Listing available breakout rooms...")
        try:
            rooms = bot.get_available_breakout_rooms()
            print(f"         Found {len(rooms)} room(s):")
            for i, r in enumerate(rooms, 1):
                marker = " <-- TARGET" if r.lower() == room_name.lower() else ""
                print(f"           {i}. {r}{marker}")
            print()
        except BreakoutRoomsNotAvailableError as e:
            print(f"\n   FAILED: Could not list rooms - {e}")
            return False

        # Step 4: Join target room
        print(f"   [4/5] Joining breakout room '{room_name}'...")
        try:
            if not bot.join_breakout_room(room_name):
                print(f"\n   FAILED: Could not join room '{room_name}'")
                return False

            print(f"         State: {bot.get_state().value}")
            print(f"         Successfully joined '{room_name}'!")
            print()

        except BreakoutRoomNotFoundError as e:
            print(f"\n   FAILED: Room not found - {e}")
            return False
        except Exception as e:
            print(f"\n   FAILED: Error joining room - {e}")
            return False

        # Step 5: Verify in breakout room
        print("   [5/5] Verifying breakout room state...")
        if bot.is_in_breakout_room():
            print("         Confirmed: In breakout room!")
        else:
            print("         Warning: Could not confirm breakout room state")
        print(f"         Final state: {bot.get_state().value}")
        print()

        # Success!
        print("   " + "=" * 40)
        print("   SUCCESS: All breakout room tests passed!")
        print("   " + "=" * 40)
        print()

        if auto_leave:
            print("   Auto-leaving breakout room...")
            if bot.leave_breakout_room():
                print("   Returned to main meeting")
            else:
                print("   Warning: Could not leave breakout room")
        else:
            print("   Bot is now in the breakout room.")
            print("   You can observe the browser window (if headed mode).")
            print()

            try:
                input("   Press Enter to leave and close browser...")
            except KeyboardInterrupt:
                print("\n\n   Interrupted...")

        return True

    except Exception as e:
        print()
        print(f"   EXCEPTION: {e}")
        print()
        import traceback

        traceback.print_exc()
        return False

    finally:
        print()
        print("   Stopping bot...")
        bot.stop()
        print("   Bot stopped.")
        print()


def list_rooms_only(
    meeting_url: str,
    bot_name: str = "Room List Bot",
    password: str = "",
    headless: bool = False,
    wait_timeout: int = 300,
) -> bool:
    """Just list available breakout rooms without joining.

    Args:
        meeting_url: Zoom meeting URL
        bot_name: Display name for the bot
        password: Meeting password (optional)
        headless: Run in headless mode
        wait_timeout: Seconds to wait for breakout rooms

    Returns:
        True if successfully listed rooms
    """
    print_header()
    print("   Mode: List rooms only (no join)")
    print()

    print_status("Meeting URL", meeting_url)
    print_status("Bot Name", bot_name)
    print()

    config = BotConfig(
        meeting_url=meeting_url,
        bot_name=bot_name,
        meeting_password=password,
        headless=headless,
        breakout_timeout_ms=wait_timeout * 1000,
    )

    bot = ZoomWebBot(config)

    try:
        print("   Joining meeting...")
        if not bot.start():
            print(f"   FAILED: {bot.error_message}")
            return False

        print("   Waiting for breakout rooms...")
        if not bot.are_breakout_rooms_available():
            if not bot.wait_for_breakout_rooms():
                print("   FAILED: Breakout rooms not available")
                return False

        print()
        print("   Available Breakout Rooms:")
        print("   " + "-" * 30)

        rooms = bot.get_available_breakout_rooms()
        for i, room in enumerate(rooms, 1):
            print(f"   {i}. {room}")

        print()
        return True

    finally:
        bot.stop()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Zoom breakout room navigation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "https://zoom.us/j/123456789" --room "Room 1"
  %(prog)s "https://zoom.us/j/123456789" --room "Room 1" --headed
  %(prog)s "https://zoom.us/j/123456789" --list-only
  %(prog)s "https://zoom.us/j/123456789" --room "Room 1" --wait 600
        """,
    )
    parser.add_argument("meeting_url", help="Zoom meeting URL to join")
    parser.add_argument(
        "--room",
        default="",
        help="Target breakout room name to join",
    )
    parser.add_argument(
        "--name",
        default="Breakout Test Bot",
        help="Bot display name (default: Breakout Test Bot)",
    )
    parser.add_argument(
        "--password",
        default="",
        help="Meeting password if required",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run in headed mode (browser visible)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (browser hidden)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=300,
        help="Seconds to wait for breakout rooms (default: 300)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list available rooms, don't join any",
    )
    parser.add_argument(
        "--auto-leave",
        action="store_true",
        help="Automatically leave breakout room after joining",
    )

    args = parser.parse_args()

    # Default to headed mode for testing unless --headless is specified
    headless = args.headless and not args.headed

    if args.list_only:
        success = list_rooms_only(
            meeting_url=args.meeting_url,
            bot_name=args.name,
            password=args.password,
            headless=headless,
            wait_timeout=args.wait,
        )
    else:
        if not args.room:
            print("Error: --room is required (or use --list-only)")
            print("Usage: python test_breakout.py <url> --room 'Room Name'")
            return 1

        success = test_breakout(
            meeting_url=args.meeting_url,
            room_name=args.room,
            bot_name=args.name,
            password=args.password,
            headless=headless,
            wait_timeout=args.wait,
            auto_leave=args.auto_leave,
        )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
