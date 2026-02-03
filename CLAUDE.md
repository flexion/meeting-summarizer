# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Live Audio Transcription with Meeting Summarization - a Python application for real-time audio transcription using faster-whisper with AWS Bedrock integration for AI-powered summarization and chat. Supports both CLI and web interfaces.

## Architecture

Two main entry points:

- **transcribe_live.py** - CLI for recording, transcription, summarization, and chat
- **web_app.py** - FastAPI web server with WebSocket-based real-time UI

Both share the same core workflow:
1. Audio capture via PyAudio → WAV recording → faster-whisper transcription → AWS Bedrock summarization/chat

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

## Development Commands

```bash
# Setup
make setup              # Create venv
source venv/bin/activate
make install            # Install dependencies
make install-dev        # Install dev dependencies (ruff, mypy)

# System dependencies (macOS)
brew install ffmpeg portaudio blackhole-2ch

# Run
make run                # CLI: python transcribe_live.py
make run-web            # Web: uvicorn web_app:app --reload

# Code quality
make format             # ruff format + ruff check --fix
make lint               # ruff check
make type-check         # mypy transcribe_live.py
```

### CLI Commands

```bash
# Record and transcribe (default)
python transcribe_live.py

# Transcribe existing audio file
python transcribe_live.py --transcribe-audio path/to/audio.wav

# Summarize existing transcript
python transcribe_live.py --summarize transcripts/transcript_*.txt

# Interactive chat with transcript
python transcribe_live.py --chat transcripts/transcript_*.txt
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
