"""
Zoom Web Client CSS Selectors.

IMPORTANT: Zoom frequently updates their web client. If the bot stops working,
check these selectors first. Use browser DevTools to inspect current DOM structure.

Last verified: 2026-02-XX (update this when verifying selectors)

Selector Strategy:
- Prefer aria-labels and data-testid attributes (more stable)
- Use text-based selectors as fallback (:has-text())
- Include multiple fallback selectors where possible
- Avoid class names that look auto-generated (e.g., "css-1abc123")
"""


class PreJoinSelectors:
    """Selectors for the pre-join/lobby screen."""

    # Name input field
    NAME_INPUT = ", ".join(
        [
            "input#inputname",
            'input[id="inputname"]',
            'input[placeholder*="name" i]',
            'input[aria-label*="name" i]',
        ]
    )

    # Join button
    JOIN_BUTTON = ", ".join(
        [
            "button#joinBtn",
            'button[id="joinBtn"]',
            "button.preview-join-button",
            'button:has-text("Join")',
        ]
    )

    # Audio mute checkbox/toggle (to join muted)
    AUDIO_MUTE = ", ".join(
        [
            'button[aria-label*="mute" i][aria-label*="audio" i]',
            'button[aria-label*="audio" i]',
            '[data-testid="preview-audio-control"]',
        ]
    )

    # Video off checkbox/toggle (to join with camera off)
    VIDEO_OFF = ", ".join(
        [
            'button[aria-label*="video" i]',
            'button[aria-label*="camera" i]',
            '[data-testid="preview-video-control"]',
        ]
    )

    # Terms/agreement dialog
    AGREE_BUTTON = ", ".join(
        [
            'button:has-text("I Agree")',
            'button:has-text("Accept")',
            'button:has-text("Agree")',
            'button[aria-label*="agree" i]',
        ]
    )

    # Password input (if meeting requires password)
    PASSWORD_INPUT = ", ".join(
        [
            "input#inputpasscode",
            'input[id="inputpasscode"]',
            'input[type="password"]',
            'input[placeholder*="password" i]',
            'input[placeholder*="passcode" i]',
        ]
    )

    # Pre-join container (to verify we're on the right page)
    PRE_JOIN_CONTAINER = ", ".join(
        [
            "#webclient",
            ".preview-container",
            '[class*="preview"]',
            "#wc-container-left",
        ]
    )


class WaitingRoomSelectors:
    """Selectors for the waiting room."""

    # Waiting room container
    WAITING_CONTAINER = ", ".join(
        [
            '[class*="waiting-room"]',
            '[data-testid="waiting-room"]',
            ".wr-content",
            "#wc-waiting-room",
        ]
    )

    # Waiting room message text
    WAITING_MESSAGE = ", ".join(
        [
            '[class*="waiting-room"] h2',
            '[class*="waiting-room-message"]',
            ".wr-title",
            ':text("Please wait")',
            ':text("host will let you in")',
        ]
    )

    # Leave waiting room button
    LEAVE_BUTTON = ", ".join(
        [
            'button:has-text("Leave")',
            'button:has-text("Leave Meeting")',
            'button[aria-label*="leave" i]',
        ]
    )

    # Text indicators that we're in waiting room
    WAITING_TEXT_INDICATORS = [
        "Please wait",
        "host will let you in",
        "waiting for the host",
        "Waiting Room",
    ]


class MeetingSelectors:
    """Selectors for the in-meeting interface."""

    # Main meeting container
    MEETING_CONTAINER = ", ".join(
        [
            "#wc-container-left",
            '[class*="meeting-client"]',
            ".meeting-app",
            "#wc-content",
        ]
    )

    # Meeting toolbar/footer
    TOOLBAR = ", ".join(
        [
            '[class*="footer"]',
            ".meeting-info-container",
            '[class*="toolbar"]',
            "#wc-footer",
        ]
    )

    # Audio button (mute/unmute)
    AUDIO_BUTTON = ", ".join(
        [
            'button[aria-label*="audio" i]',
            'button[aria-label*="mute" i]',
            '[data-testid="audio-btn"]',
            '.footer-button-base__button[aria-label*="audio" i]',
        ]
    )

    # Join audio by computer button (appears after joining)
    JOIN_AUDIO_BUTTON = ", ".join(
        [
            'button:has-text("Join Audio by Computer")',
            'button:has-text("Join Audio")',
            'button:has-text("Computer Audio")',
            '[aria-label*="Join Audio" i]',
        ]
    )

    # Participant count
    PARTICIPANT_COUNT = ", ".join(
        [
            '[class*="participants-count"]',
            '[aria-label*="participants"]',
            ".footer-button-base__number",
        ]
    )

    # Leave meeting button
    LEAVE_BUTTON = ", ".join(
        [
            'button[aria-label*="leave" i]',
            'button:has-text("Leave")',
            'button:has-text("End")',
            ".footer__leave-btn",
        ]
    )

    # Video grid (indicates we're in a meeting)
    VIDEO_CONTAINER = ", ".join(
        [
            '[class*="video-container"]',
            ".gallery-video-container",
            "#wc-video",
        ]
    )


class ErrorSelectors:
    """Selectors for error states and messages."""

    # Generic error message container
    ERROR_CONTAINER = ", ".join(
        [
            '[class*="error"]',
            ".zm-modal-body-message",
            '[role="alert"]',
        ]
    )

    # Meeting ended message
    MEETING_ENDED = ", ".join(
        [
            ':text("meeting has ended")',
            ':text("Meeting has been ended")',
            ':text("host has ended")',
            ':text("This meeting has ended")',
        ]
    )

    # Invalid meeting ID
    INVALID_MEETING = ", ".join(
        [
            ':text("Invalid meeting ID")',
            ':text("does not exist")',
            ':text("meeting ID is not valid")',
            ':text("Please check")',
        ]
    )

    # Meeting not started
    NOT_STARTED = ", ".join(
        [
            ':text("has not started")',
            ':text("not yet started")',
            ':text("Waiting for host")',
        ]
    )

    # Removed from meeting
    REMOVED = ", ".join(
        [
            ':text("removed from")',
            ':text("been removed")',
            ':text("kicked")',
        ]
    )

    # Host ended meeting (more specific than general MEETING_ENDED)
    HOST_ENDED_MEETING = ", ".join(
        [
            ':text("host ended the meeting")',
            ':text("meeting has been ended by host")',
            ':text("This meeting has been ended")',
            ':text("The host has ended this meeting")',
        ]
    )


class BreakoutRoomSelectors:
    """Selectors for breakout room UI.

    Note: These selectors may need adjustment based on Zoom's web client version.
    The web client UI varies and Zoom updates it periodically.
    """

    # Breakout rooms button in toolbar
    BREAKOUT_BUTTON = ", ".join(
        [
            'button[aria-label*="Breakout" i]',
            'button:has-text("Breakout Rooms")',
            '[data-testid="breakout-rooms-btn"]',
            '[class*="breakout-room-btn"]',
        ]
    )

    # Breakout room list container/panel
    ROOM_LIST = ", ".join(
        [
            '[class*="breakout-room-list"]',
            '[class*="bo-room-list"]',
            '[aria-label*="breakout room" i]',
            '[class*="breakout-rooms-panel"]',
            '[role="dialog"][aria-label*="Breakout" i]',
        ]
    )

    # Individual room item in the list
    ROOM_ITEM = ", ".join(
        [
            '[class*="breakout-room-item"]',
            '[class*="bo-room-item"]',
            'li[class*="room"]',
            '[class*="room-item"]',
        ]
    )

    # Room name text within a room item
    ROOM_NAME = ", ".join(
        [
            '[class*="room-name"]',
            '[class*="bo-room-item-container__name"]',
            'span[class*="name"]',
            '[class*="room-title"]',
        ]
    )

    # Join room button (within room item or after selection)
    JOIN_ROOM_BUTTON = ", ".join(
        [
            'button:has-text("Join")',
            'button[aria-label*="Join" i]',
            '[class*="join-btn"]',
            '[class*="join-room"]',
        ]
    )

    # Leave breakout room button (visible only when in breakout room)
    LEAVE_ROOM_BUTTON = ", ".join(
        [
            'button:has-text("Leave Room")',
            'button:has-text("Leave Breakout Room")',
            'button[aria-label*="Leave Room" i]',
            '[class*="leave-room"]',
        ]
    )

    # Participant count in room (optional, for room info)
    ROOM_PARTICIPANT_COUNT = ", ".join(
        [
            '[class*="participant-count"]',
            '[class*="room-count"]',
            'span[class*="count"]',
        ]
    )

    # Indicator that we're in a breakout room (shown in header/UI)
    IN_BREAKOUT_INDICATOR = ", ".join(
        [
            '[class*="breakout-room-header"]',
            ':text("Breakout Room")',
            '[class*="in-breakout"]',
        ]
    )

    # Indicator that breakout room is closing soon
    BREAKOUT_CLOSING_SOON = ", ".join(
        [
            ':text("closing soon")',
            ':text("will close in")',
            ':text("returning to main")',
            ':text("Breakout Rooms will close")',
            ':text("seconds remaining")',
        ]
    )
