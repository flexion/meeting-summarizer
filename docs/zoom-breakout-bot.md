# Zoom Breakout Room Bot

## Overview

A headless browser bot that joins Zoom meetings via the web client and can autonomously navigate to breakout rooms when they become available. The bot captures audio directly from the browser and feeds it to our existing faster-whisper transcription pipeline.

## Problem Statement

When using Zoom's breakout rooms, there's no easy way to automatically transcribe individual rooms. Current solutions either:
- Require host intervention to assign bots to rooms
- Don't support breakout rooms at all
- Rely on post-meeting cloud recordings

We want a bot that can **self-select** a breakout room (when "Allow participants to choose room" is enabled) and transcribe that room in real-time.

## Solution

Use Playwright to automate a headless Chrome browser that:
1. Joins the Zoom meeting as a web participant
2. Waits for breakout rooms to open
3. Selects a specific room by name
4. Captures audio from the browser session
5. Transcribes using our existing faster-whisper pipeline

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Playwright (Chrome)                        │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Zoom Web Client                            │ │
│  │                                                         │ │
│  │  - Joins meeting as participant                         │ │
│  │  - Receives audio via WebRTC                            │ │
│  │  - UI shows breakout room selection                     │ │
│  └──────────────────────┬─────────────────────────────────┘ │
│                         │                                    │
│                         ▼                                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │     Web Audio API (Injected JavaScript)                 │ │
│  │                                                         │ │
│  │  - Hooks HTMLMediaElement.play()                        │ │
│  │  - Hooks RTCPeerConnection.ontrack                      │ │
│  │  - ScriptProcessorNode captures audio buffers           │ │
│  │  - Base64 encode → page.expose_function()               │ │
│  └──────────────────────┬─────────────────────────────────┘ │
└─────────────────────────┼───────────────────────────────────┘
                          │ (48kHz, stereo, float32)
                          ▼
              ┌───────────────────────┐
              │    AudioProcessor     │
              │                       │
              │  - scipy resample     │
              │  - stereo → mono      │
              │  - float32 → int16    │
              └───────────┬───────────┘
                          │ (16kHz, mono, int16)
                          ▼
              ┌───────────────────────┐
              │   WAV File Output     │
              │   (crash-safe write)  │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │    faster-whisper     │
              │    (transcription)    │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Transcript Output   │
              │   + AWS Bedrock       │
              │   (summarization)     │
              └───────────────────────┘
```

## User Story

> As a meeting organizer, I want to automatically transcribe a specific breakout room so that I can capture discussions without manually assigning a recording bot or relying on cloud recordings.

### Acceptance Criteria

- [x] Bot can join a Zoom meeting via URL *(Phase 1)*
- [x] Bot can enter a display name *(Phase 1)*
- [x] Bot can handle waiting room (wait to be admitted) *(Phase 1)*
- [x] Bot can detect when breakout rooms become available *(Phase 2)*
- [x] Bot can view the list of available breakout rooms *(Phase 2)*
- [x] Bot can join a specific breakout room by name *(Phase 2)*
- [x] Bot can capture audio from the meeting/breakout room *(Phase 3)*
- [x] Bot outputs WAV file compatible with existing transcription pipeline *(Phase 3)*
- [x] Bot detects when meeting ends and stops gracefully *(Phase 4)*
- [x] Bot detects when returned to main meeting from breakout room *(Phase 4)*

## Requirements

### Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Join Zoom meeting via web URL | Must |
| FR-2 | Configure bot display name | Must |
| FR-3 | Handle waiting room flow | Must |
| FR-4 | Detect breakout room availability | Must |
| FR-5 | List available breakout rooms | Must |
| FR-6 | Join breakout room by name | Must |
| FR-7 | Capture audio from browser session | Must |
| FR-8 | Output WAV file compatible with faster-whisper | Must |
| FR-9 | Transcribe via existing CLI (post-recording) | Should |
| FR-10 | Handle meeting end gracefully | Should |
| FR-11 | Handle breakout room closing | Should |
| FR-12 | Rejoin main room when breakout closes | Could |

### Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-1 | macOS support | Must |
| NFR-2 | Headless operation (no GUI) | Must |
| NFR-3 | Configurable via environment variables | Should |
| NFR-4 | Logging for debugging | Should |
| NFR-5 | Error recovery on transient failures | Could |

### Constraints

- macOS only (for now)
- Requires "Allow participants to choose room" enabled in Zoom
- Web client must be allowed by meeting host
- Bot appears as a visible participant in the meeting

## Technical Approach

### Browser Automation

- **Playwright** with Chromium
- Navigate to `https://zoom.us/wc/join/{meeting_id}`
- Automate pre-join form (name, audio/video settings)
- Handle consent dialogs and popups
- Scrape DOM to detect breakout room UI elements

### Audio Capture

**Chosen approach: Web Audio API JavaScript Injection**

Alternatives considered and rejected:
- **Chrome DevTools Protocol (CDP)** - Cannot extract raw audio streams
- **Chrome extension** - Conflicts with headless mode

Implementation:
1. Inject JavaScript via `page.evaluate()` to hook media elements and WebRTC
2. Use `ScriptProcessorNode` to capture audio buffers (4096 samples)
3. Base64 encode and send to Python via `page.expose_function()`
4. Python `AudioProcessor` converts format: 48kHz stereo → 16kHz mono
5. Write to WAV file incrementally using scipy for high-quality resampling

### Breakout Room Navigation

1. Watch for "Breakout Rooms" button in toolbar (appears when rooms open)
2. Click to open room list panel
3. Parse room names from DOM
4. Find target room by name matching
5. Click "Join" button for that room
6. Detect successful room transition

### Integration with Existing Pipeline

- Output WAV file (16kHz, mono, 16-bit PCM) - same format as `transcribe_live.py`
- Transcribe post-recording using existing CLI: `python transcribe_live.py --transcribe-audio <wav_file>`
- Or use `--transcribe` flag in test script for automatic transcription
- Optionally summarize with AWS Bedrock

## Tasks

### Phase 1: Playwright Setup & Meeting Join ✅ COMPLETE

- [x] Set up Playwright project structure
- [x] Implement meeting join via URL
- [x] Handle name entry screen
- [x] Handle "Join Audio" dialog
- [x] Handle waiting room detection and waiting
- [x] Detect successful meeting join
- [x] Add basic logging

**Implementation Notes (Phase 1):**
- Created `playwright_bot/` module with Page Object Model pattern
- Files: `zoom_web_bot.py`, `selectors.py`, `exceptions.py`, page objects
- State machine: IDLE → LAUNCHING → NAVIGATING → PRE_JOIN → JOINING → WAITING_ROOM → IN_MEETING
- Test script: `python playwright_bot/test_join.py <url> --headed`
- Added Playwright to requirements.txt and Makefile targets

### Phase 2: Breakout Room Navigation ✅ COMPLETE

- [x] Detect breakout room button appearance
- [x] Implement click to open room list
- [x] Parse room names from DOM
- [x] Implement room selection by name
- [x] Handle "Join" button click
- [x] Detect successful breakout room join
- [x] Handle room not found error

**Implementation Notes (Phase 2):**
- Created `BreakoutRoomPage` page object for all breakout room interactions
- Added 3 new bot states: `WAITING_FOR_BREAKOUT`, `JOINING_BREAKOUT`, `IN_BREAKOUT_ROOM`
- Added `breakout_room` and `breakout_timeout_ms` to `BotConfig`
- New methods on `ZoomWebBot`: `wait_for_breakout_rooms()`, `get_available_breakout_rooms()`, `join_breakout_room()`, `leave_breakout_room()`, `is_in_breakout_room()`, `are_breakout_rooms_available()`
- Test script: `python playwright_bot/test_breakout.py <url> --room "Room 1" --headed`
- Added `run-breakout-test` Makefile target

### Phase 3: Audio Capture ✅ COMPLETE

- [x] Research CDP audio capture capabilities
- [x] Prototype audio stream interception
- [x] Convert captured audio to PCM format
- [x] Verify audio quality/format for whisper

**Implementation Notes (Phase 3):**
- Created `playwright_bot/audio/` module for audio capture and processing
- Uses Web Audio API JavaScript injection (CDP cannot extract raw audio streams)
- Hooks `HTMLMediaElement.prototype.play` and `RTCPeerConnection.ontrack` to intercept audio
- Audio captured via `ScriptProcessorNode`, base64 encoded, sent to Python via `page.expose_function()`
- `AudioProcessor` converts 48kHz stereo float32 → 16kHz mono int16 using scipy
- WAV files written incrementally for crash safety
- Test script: `python playwright_bot/test_audio.py <url> --headed` (runs until Ctrl+C)
- Added `run-audio-test` Makefile target and `scipy>=1.10.0` dependency

### Phase 4: Polish ✅ COMPLETE

- [x] Handle meeting end detection
- [x] Handle breakout room close (return to main meeting)
- [x] Background meeting status monitoring
- [x] Auto-stop audio capture when meeting ends
- [x] Graceful state transitions

**Implementation Notes (Phase 4):**
- Created `MeetingMonitor` class with background polling (2s interval)
- Added `MEETING_ENDED` state to `BotState` enum
- Added `MeetingEvent` enum: `MEETING_ENDED`, `REMOVED_FROM_MEETING`, `BREAKOUT_CLOSING_SOON`, `RETURNED_TO_MAIN`
- New selectors for detecting meeting end and breakout room closing
- Bot automatically stops audio capture and updates state when meeting ends
- Monitor detects when returned to main meeting from breakout room

## Configuration

Environment variables (see `.env.example`):

```bash
# Meeting settings
ZOOM_MEETING_URL=https://zoom.us/j/123456789
ZOOM_BOT_NAME="Transcription Bot"
ZOOM_MEETING_PASSWORD=           # Optional
ZOOM_BREAKOUT_ROOM="Room 1"      # Target room name (Phase 2)

# Playwright settings
PLAYWRIGHT_HEADLESS=true         # Run browser headless
PLAYWRIGHT_TIMEOUT=60000         # Default timeout (ms)
PLAYWRIGHT_SLOWMO=0              # Slow down for debugging
PLAYWRIGHT_DEBUG=false           # Enable verbose logging
PLAYWRIGHT_SCREENSHOTS=true      # Take screenshots on errors

# Transcription settings (existing)
WHISPER_MODEL=large-v3-turbo
DEVICE=cpu
COMPUTE_TYPE=int8
OUTPUT_DIR=transcripts
```

### BotConfig Options (Phase 3)

```python
@dataclass
class BotConfig:
    meeting_url: str
    bot_name: str = "Transcription Bot"
    meeting_password: str = ""
    breakout_room: str = ""              # Target breakout room name
    headless: bool = True
    timeout_ms: int = 60000
    waiting_room_timeout_ms: int = 300000
    breakout_timeout_ms: int = 300000
    screenshot_on_error: bool = True
    enable_audio_capture: bool = True    # Enable audio capture (Phase 3)
    audio_output_dir: str = "transcripts" # Audio output directory (Phase 3)
```

## Open Questions

1. ~~**Audio capture method** - Which approach (CDP, injection, extension) works best with Zoom's web client?~~ **Answered:** Web Audio API injection via `page.evaluate()` works well
2. **Zoom web client compatibility** - Does Zoom block headless browsers or automation? *Testing ongoing*
3. ~~**Audio format** - What format does Zoom's WebRTC stream use? Will it need conversion?~~ **Answered:** 48kHz stereo float32, converted to 16kHz mono int16 for Whisper
4. **Rate limiting** - Will Zoom throttle or block automated joins?
5. **Selector stability** - How often does Zoom change their web client DOM structure?

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Zoom blocks headless browsers | Medium | High | Use non-headless mode, add human-like delays |
| DOM selectors break on Zoom update | High | Medium | Use resilient selectors, monitor for changes |
| ~~Audio capture doesn't work~~ | ~~Medium~~ | ~~High~~ | ✅ **Resolved** - Web Audio API injection works |
| Poor audio quality | Low | Medium | Test with actual meetings, adjust capture method |
| ScriptProcessorNode deprecated | Low | Medium | Prepare AudioWorklet migration path |
| High CPU from audio processing | Medium | Low | Use efficient numpy operations, batch processing |

## Future Enhancements

- Real-time transcription (streaming audio to faster-whisper during recording)
- Linux/Docker support
- Multiple concurrent bots (one per breakout room)
- Automatic room discovery and assignment
- Real-time transcript streaming via WebSocket
- Integration with meeting calendar for scheduled joins

---

## Implementation Progress

### Phase 1: Playwright Setup & Meeting Join ✅

**Completed:** 2026-02-02

**Files Created:**
```
playwright_bot/
├── __init__.py                     # Package exports
├── exceptions.py                   # Custom exceptions
├── selectors.py                    # Centralized CSS selectors
├── zoom_web_bot.py                 # Main bot controller (900+ lines)
├── meeting_monitor.py              # Background meeting status monitor (Phase 4)
├── test_join.py                    # Test script
├── test_breakout.py                # Breakout room test script (Phase 2)
├── test_audio.py                   # Audio capture test script (Phase 3)
├── audio/                          # Audio capture module (Phase 3)
│   ├── __init__.py
│   ├── exceptions.py
│   ├── capturer.py
│   └── processor.py
└── page_objects/
    ├── __init__.py
    ├── pre_join_page.py            # Pre-join screen handling
    ├── waiting_room_page.py        # Waiting room handling
    ├── meeting_page.py             # In-meeting detection + status monitoring (Phase 4)
    └── breakout_room_page.py       # Breakout room handling (Phase 2 + 4)
```

**Files Modified:**
- `requirements.txt` - Added `playwright>=1.40.0`, `scipy>=1.10.0`
- `.env.example` - Added Playwright config variables
- `Makefile` - Added `install-playwright`, `run-playwright-test`, `run-breakout-test`, `run-audio-test` targets
- `pyproject.toml` - Added Playwright to mypy overrides

**Key Features:**
- State machine with 9 states (IDLE → IN_MEETING)
- Page Object Model for maintainable selectors
- Centralized selectors in `selectors.py` for easy updates
- Error screenshots saved to `transcripts/`
- Configurable timeouts and headless mode

**Usage:**
```bash
# Install Playwright browser
make install-playwright

# Test join flow (headed mode)
python playwright_bot/test_join.py "https://zoom.us/j/123456789" --headed

# Or via Makefile
make run-playwright-test URL="https://zoom.us/j/123456789"
```

### Phase 2: Breakout Room Navigation ✅

**Completed:** 2026-02-03

**Files Created:**
```
playwright_bot/
├── page_objects/
│   └── breakout_room_page.py    # Breakout room interactions (350+ lines)
└── test_breakout.py             # Breakout room test script (280+ lines)
```

**Files Modified:**
- `playwright_bot/zoom_web_bot.py` - Added breakout states, config, and methods
- `playwright_bot/selectors.py` - Enhanced breakout room selectors
- `playwright_bot/__init__.py` - Exported BreakoutRoomPage
- `playwright_bot/page_objects/__init__.py` - Exported BreakoutRoomPage
- `Makefile` - Added `run-breakout-test` target

**Key Features:**
- State machine extended to 12 states (added WAITING_FOR_BREAKOUT, JOINING_BREAKOUT, IN_BREAKOUT_ROOM)
- Wait for breakout rooms to become available (configurable timeout)
- List all available breakout rooms
- Join room by name (case-insensitive matching)
- Detect when in breakout room vs main meeting
- Leave breakout room and return to main meeting

**Usage:**
```bash
# Test breakout room flow (headed mode)
python playwright_bot/test_breakout.py "https://zoom.us/j/123" --room "Room 1" --headed

# List available rooms only
python playwright_bot/test_breakout.py "https://zoom.us/j/123" --list-only

# Via Makefile
make run-breakout-test URL="https://zoom.us/j/123" ROOM="Room 1"
```

### Phase 3: Audio Capture ✅

**Completed:** 2026-02-03

**Files Created:**
```
playwright_bot/
├── audio/
│   ├── __init__.py              # Package exports
│   ├── exceptions.py            # AudioCaptureError, AudioProcessingError
│   ├── capturer.py              # AudioCapturer - JS injection for browser audio (450+ lines)
│   └── processor.py             # AudioProcessor - format conversion (250+ lines)
└── test_audio.py                # Audio capture test script (300+ lines)
```

**Files Modified:**
- `playwright_bot/zoom_web_bot.py` - Added RECORDING state, audio config, capture methods
- `requirements.txt` - Added `scipy>=1.10.0`
- `Makefile` - Added `run-audio-test` target

**Key Features:**
- Web Audio API JavaScript injection to intercept browser audio
- Hooks `HTMLMediaElement.prototype.play` for media elements
- Hooks `RTCPeerConnection.ontrack` for WebRTC streams (Zoom)
- Uses `ScriptProcessorNode` to capture audio buffers
- Base64 encoding for transfer to Python via `page.expose_function()`
- High-quality resampling with scipy (48kHz → 16kHz)
- Stereo to mono conversion
- Float32 to Int16 conversion
- Incremental WAV file writing (crash-safe)

**Audio Pipeline:**
```
Zoom WebRTC Audio (48kHz, stereo, float32)
    ↓
ScriptProcessorNode (buffer_size=4096)
    ↓
Base64 encode → page.expose_function()
    ↓
Python AudioProcessor
    ↓
scipy.signal.resample (48kHz → 16kHz)
    ↓
Stereo → Mono, Float32 → Int16
    ↓
WAV File (16kHz, mono, 16-bit PCM)
```

**New Bot Methods:**
- `start_audio_capture()` - Begin capturing audio from browser
- `stop_audio_capture()` - Stop capture, returns (wav_path, duration)
- `is_recording()` - Check if currently recording
- `get_recording_duration()` - Get current recording duration
- `get_recording_path()` - Get path to WAV file

**New Config Options:**
- `enable_audio_capture: bool = True` - Enable/disable audio capture
- `audio_output_dir: str = "transcripts"` - Output directory for recordings

**Usage:**
```bash
# Basic audio capture test (runs until Ctrl+C)
make run-audio-test URL="https://zoom.us/j/123456789"

# Headed mode with specific duration (60 seconds)
make run-audio-test URL="https://zoom.us/j/123456789" HEADED=1 DURATION=60

# Test with transcription (runs until Ctrl+C)
python playwright_bot/test_audio.py "https://zoom.us/j/123" --headed --transcribe

# Test in breakout room (runs until Ctrl+C)
python playwright_bot/test_audio.py "https://zoom.us/j/123" --room "Room 1"
```

### Phase 4: Polish ✅

**Completed:** 2026-02-03

**Files Created:**
```
playwright_bot/
└── meeting_monitor.py              # Background meeting status monitor (180+ lines)
```

**Files Modified:**
- `playwright_bot/zoom_web_bot.py` - Added `MEETING_ENDED` state, monitor integration, event handlers
- `playwright_bot/selectors.py` - Added `BREAKOUT_CLOSING_SOON`, `HOST_ENDED_MEETING` selectors
- `playwright_bot/page_objects/meeting_page.py` - Added `is_meeting_active()`, `get_meeting_status()`
- `playwright_bot/page_objects/breakout_room_page.py` - Added `is_breakout_closing_soon()`, `has_returned_to_main_meeting()`

**Key Features:**
- Background `MeetingMonitor` thread polls every 2 seconds for status changes
- Detects when host ends meeting or bot is removed/kicked
- Detects when breakout rooms are closing soon
- Detects when returned to main meeting from breakout room
- Automatically stops audio capture and saves WAV when meeting ends
- State machine correctly transitions: `IN_MEETING` → `MEETING_ENDED`, `IN_BREAKOUT_ROOM` → `IN_MEETING`

**Events Detected:**
```python
class MeetingEvent(Enum):
    MEETING_ENDED = "meeting_ended"
    REMOVED_FROM_MEETING = "removed_from_meeting"
    BREAKOUT_CLOSING_SOON = "breakout_closing_soon"
    RETURNED_TO_MAIN = "returned_to_main"
```

**State Transitions:**
```
IN_MEETING + MEETING_ENDED → MEETING_ENDED (audio saved)
IN_MEETING + REMOVED_FROM_MEETING → MEETING_ENDED (audio saved)
IN_BREAKOUT_ROOM + MEETING_ENDED → MEETING_ENDED (audio saved)
IN_BREAKOUT_ROOM + REMOVED_FROM_MEETING → MEETING_ENDED (audio saved)
IN_BREAKOUT_ROOM + RETURNED_TO_MAIN → IN_MEETING
```

**Usage:**
The meeting monitor starts automatically after successfully joining a meeting. No additional configuration needed.

```bash
# Test with headed mode - observe behavior when host ends meeting (runs until Ctrl+C or meeting ends)
python playwright_bot/test_audio.py "https://zoom.us/j/123" --headed

# Bot will:
# 1. Join meeting
# 2. Start audio capture
# 3. If host ends meeting → detect, stop capture, save WAV, transition to MEETING_ENDED
# 4. If in breakout room and host closes rooms → detect, transition back to IN_MEETING
```
