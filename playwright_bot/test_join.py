#!/usr/bin/env python3
"""Test script to verify Zoom web bot join flow.

Usage:
    python playwright_bot/test_join.py "https://zoom.us/j/123456789"
    python playwright_bot/test_join.py "https://zoom.us/j/123456789" --password "abc123"
    python playwright_bot/test_join.py "https://zoom.us/j/123456789" --headed

This script runs the bot in headed mode by default for visual verification.
"""

from __future__ import annotations

import argparse
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

from playwright_bot.zoom_web_bot import BotConfig, BotState, ZoomWebBot


def print_header() -> None:
    """Print the test header."""
    print()
    print("=" * 60)
    print("   Playwright Zoom Bot - Join Test")
    print("=" * 60)
    print()


def print_status(label: str, value: str, indent: int = 3) -> None:
    """Print a status line."""
    spaces = " " * indent
    print(f"{spaces}{label}: {value}")


def test_join(
    meeting_url: str,
    bot_name: str = "Test Bot",
    password: str = "",
    headless: bool = False,
) -> bool:
    """Test the meeting join flow.

    Args:
        meeting_url: Zoom meeting URL
        bot_name: Display name for the bot
        password: Meeting password (optional)
        headless: Run in headless mode

    Returns:
        True if join was successful
    """
    print_header()

    print_status("Meeting URL", meeting_url)
    print_status("Bot Name", bot_name)
    print_status("Password", "***" if password else "(none)")
    print_status("Headless", str(headless))
    print()

    config = BotConfig(
        meeting_url=meeting_url,
        bot_name=bot_name,
        meeting_password=password,
        headless=headless,
        screenshot_on_error=True,
    )

    bot = ZoomWebBot(config)

    try:
        print("   Starting bot...")
        print()

        if bot.start():
            print()
            print("   " + "=" * 40)
            print("   SUCCESS: Joined meeting!")
            print("   " + "=" * 40)
            print()
            print_status("Current State", bot.get_state().value)

            # Display some meeting info
            if bot._meeting_page:
                participant_count = bot._meeting_page.get_participant_count()
                if participant_count:
                    print_status("Participants", str(participant_count))

                audio_connected = bot._meeting_page.is_audio_connected()
                print_status("Audio Connected", str(audio_connected))

            print()
            print("   The bot is now in the meeting.")
            print("   You can observe the browser window (if headed mode).")
            print()

            # Keep bot running until user wants to leave
            try:
                input("   Press Enter to leave meeting and close browser...")
            except KeyboardInterrupt:
                print("\n\n   Interrupted, leaving meeting...")

            return True

        else:
            print()
            print("   " + "=" * 40)
            print("   FAILED: Could not join meeting")
            print("   " + "=" * 40)
            print()
            print_status("State", bot.get_state().value)
            if bot.error_message:
                print_status("Error", bot.error_message)

            print()
            print("   Check the error screenshot in the transcripts/ directory")
            print("   for debugging information.")
            print()

            return False

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


def test_state_transitions(
    meeting_url: str,
    bot_name: str = "State Test Bot",
    headless: bool = True,
) -> None:
    """Test and log all state transitions during join.

    Args:
        meeting_url: Zoom meeting URL
        bot_name: Display name for the bot
        headless: Run in headless mode
    """
    print_header()
    print("   Running state transition test...")
    print()

    config = BotConfig(
        meeting_url=meeting_url,
        bot_name=bot_name,
        headless=headless,
        timeout_ms=30000,
        waiting_room_timeout_ms=60000,  # 1 minute for testing
    )

    bot = ZoomWebBot(config)
    states_seen: list[BotState] = []

    # Patch the state update method to log transitions
    original_update = bot._update_state

    def logging_update(new_state: BotState) -> None:
        states_seen.append(new_state)
        print(f"      -> {new_state.value}")
        original_update(new_state)

    bot._update_state = logging_update  # type: ignore

    try:
        print("   State transitions:")
        print()
        success = bot.start()
        print()

        if success:
            print(f"   Final state: {bot.get_state().value}")
            print()

            # Let it sit for a moment
            time.sleep(2)

        print(f"   States seen: {[s.value for s in states_seen]}")

    finally:
        bot.stop()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Zoom web bot join flow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "https://zoom.us/j/123456789"
  %(prog)s "https://zoom.us/j/123456789" --password "abc123"
  %(prog)s "https://zoom.us/j/123456789" --headed
  %(prog)s "https://zoom.us/j/123456789" --test-states
        """,
    )
    parser.add_argument("meeting_url", help="Zoom meeting URL to join")
    parser.add_argument(
        "--name",
        default="Test Bot",
        help="Bot display name (default: Test Bot)",
    )
    parser.add_argument(
        "--password",
        default="",
        help="Meeting password if required",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run in headed mode (browser visible) - default for test script",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (browser hidden)",
    )
    parser.add_argument(
        "--test-states",
        action="store_true",
        help="Run state transition test instead of normal join test",
    )

    args = parser.parse_args()

    # Default to headed mode for testing unless --headless is specified
    headless = args.headless and not args.headed

    if args.test_states:
        test_state_transitions(
            meeting_url=args.meeting_url,
            bot_name=args.name,
            headless=headless,
        )
        return 0
    else:
        success = test_join(
            meeting_url=args.meeting_url,
            bot_name=args.name,
            password=args.password,
            headless=headless,
        )
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
