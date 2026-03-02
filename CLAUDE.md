# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Live Audio Transcription with Meeting Summarization - a Python application for real-time audio transcription using faster-whisper with AWS Bedrock integration for AI-powered summarization and chat. Supports CLI, web interfaces, and a headless Zoom bot for automatic meeting transcription.

## Architecture

Three main entry points:

- **transcribe_live.py** - CLI for recording, transcription, summarization, and chat
- **web_app.py** - FastAPI web server with WebSocket-based real-time UI
- **playwright_bot/** - Headless Zoom bot for automatic meeting transcription

CLI and web app share the same core workflow:
1. Audio capture via PyAudio → WAV recording → faster-whisper transcription → AWS Bedrock summarization/chat

Zoom bot workflow:
1. Playwright browser → Zoom web client → Web Audio API capture → WAV recording → faster-whisper transcription

### Data Flow

```
Audio Source (Microphone/System Audio)
  ↓
BlackHole Virtual Audio Device (macOS)
  ↓
PyAudio Stream (16kHz, Mono, 16-bit)
  ↓
WAV File Recording (crash-safe)
  ↓
faster-whisper Transcription (post-recording)
  ↓
Timestamped Transcript → Console/Web UI
  ↓
AWS Bedrock Claude → Summary/Chat
```

### Web App Architecture (web_app.py)

- **FastAPI** REST endpoints for control (`/api/start`, `/api/stop`, `/api/chat`)
- **WebSocket** at `/ws` for real-time audio levels and transcription progress
- **TranscriptionState** class manages thread-safe session state
- **ConnectionManager** handles WebSocket broadcast to multiple clients
- Background thread for audio capture; async task for client broadcasts

### Zoom Bot Architecture (playwright_bot/)

```
playwright_bot/
├── zoom_web_bot.py          # Main bot controller, state machine
├── meeting_monitor.py       # Background thread for meeting status
├── selectors.py             # Centralized CSS selectors for Zoom UI
├── exceptions.py            # Custom exceptions
├── audio/
│   ├── capturer.py          # Web Audio API injection for browser audio
│   └── processor.py         # Audio format conversion (48kHz→16kHz)
└── page_objects/
    ├── pre_join_page.py     # Pre-join screen handling
    ├── waiting_room_page.py # Waiting room handling
    ├── meeting_page.py      # In-meeting detection + status
    └── breakout_room_page.py # Breakout room navigation
```

**Bot State Machine:**
```
IDLE → LAUNCHING → NAVIGATING → PRE_JOIN → JOINING → WAITING_ROOM → IN_MEETING
                                                                    ↓
                                          IN_BREAKOUT_ROOM ← JOINING_BREAKOUT
                                                    ↓
                                              MEETING_ENDED
```

**Audio Capture Flow:**
```
Zoom WebRTC (48kHz stereo) → ScriptProcessorNode → Base64 → Python
    → scipy resample (16kHz mono) → WAV file
```

## Development Commands

This project uses [uv](https://docs.astral.sh/uv/) for package management. Install uv first: `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`.

```bash
# Setup
make setup              # Create .venv with uv
source .venv/bin/activate
make install            # Install production dependencies (uv sync --no-group dev)
make install-dev        # Install all dependencies including dev (uv sync + pre-commit install)

# System dependencies (macOS)
brew install ffmpeg portaudio blackhole-2ch

# Run
make run                # CLI: uv run python transcribe_live.py
make run-web            # Web: uv run python -m uvicorn web_app:app --reload

# Code quality
make format             # ruff format + ruff check --fix
make lint               # ruff check
make type-check         # mypy transcribe_live.py

# Zoom Bot
make install-playwright # Install Playwright browser
make run-audio-test URL="https://zoom.us/j/123" HEADED=1  # Runs until Ctrl+C
make run-audio-test URL="https://zoom.us/j/123" HEADED=1 DURATION=60  # Runs for 60s
make run-breakout-test URL="https://zoom.us/j/123" ROOM="Room 1"
```

### CLI Commands

```bash
# Record and transcribe (default)
uv run python transcribe_live.py

# Transcribe existing audio file
uv run python transcribe_live.py --transcribe-audio path/to/audio.wav

# Summarize existing transcript
uv run python transcribe_live.py --summarize transcripts/transcript_*.txt

# Interactive chat with transcript
uv run python transcribe_live.py --chat transcripts/transcript_*.txt
```

### Zoom Bot Commands

```bash
# Join meeting and capture audio (runs until Ctrl+C)
uv run python playwright_bot/test_audio.py "https://zoom.us/j/123" --headed

# Join meeting with specific duration (60 seconds)
uv run python playwright_bot/test_audio.py "https://zoom.us/j/123" --headed --duration 60

# Join meeting headless with transcription
uv run python playwright_bot/test_audio.py "https://zoom.us/j/123" --transcribe

# Join specific breakout room
uv run python playwright_bot/test_audio.py "https://zoom.us/j/123" --room "Room 1"

# List available breakout rooms
uv run python playwright_bot/test_breakout.py "https://zoom.us/j/123" --list-only

# Test meeting join only (no audio)
uv run python playwright_bot/test_join.py "https://zoom.us/j/123" --headed
```

## Configuration

Environment variables via `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| WHISPER_MODEL | large-v3 | Model size (tiny/base/small/medium/large-v3) |
| DEVICE | cpu | Compute device (cpu/cuda) |
| COMPUTE_TYPE | int8 | Quantization (int8/float16/float32) |
| OUTPUT_DIR | transcripts | Output directory for recordings/transcripts |
| AWS_REGION | us-east-1 | AWS region for Bedrock |
| BEDROCK_MODEL_ID | global.anthropic.claude-sonnet-4-5-20250929-v1:0 | Claude model for summarization |
| WEB_HOST | 127.0.0.1 | Web server host |
| WEB_PORT | 8000 | Web server port |
| PLAYWRIGHT_HEADLESS | true | Run Zoom bot browser headless |
| PLAYWRIGHT_TIMEOUT | 60000 | Bot timeout in ms |
| PLAYWRIGHT_DEBUG | false | Enable verbose bot logging |

## Key Implementation Details

### Audio Settings (both scripts)
```python
RATE = 16000      # Whisper expects 16kHz
CHANNELS = 1      # Mono
CHUNK = 1024      # Buffer size
FORMAT = pyaudio.paInt16
```

### Thread Safety (web_app.py)
- `TranscriptionState` uses `threading.Lock` for all state mutations
- Audio capture runs in background thread; WebSocket broadcast in async task
- Queue-based communication between threads

### Transcription Workflow
1. Record to WAV file incrementally (crash-safe)
2. After recording stops, transcribe full WAV file
3. faster-whisper handles long files with internal VAD filtering
4. Timestamps formatted as `[MM:SS]` or `[HH:MM:SS]`

### AWS Bedrock Integration
- Uses Claude via `boto3.client("bedrock-runtime")`
- Requires AWS credentials (`~/.aws/credentials` or environment variables)
- Chat maintains conversation history for multi-turn dialogue

## File Outputs

All outputs saved to `transcripts/` directory:
- `recording_YYYY-MM-DD_HH-MM-SS.wav` - Audio recording
- `transcript_YYYY-MM-DD_HH-MM-SS.txt` - Timestamped transcript with metadata and summary
