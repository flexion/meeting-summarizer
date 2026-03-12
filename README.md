# Live Audio Transcription

Real-time audio transcription using faster-whisper and BlackHole for macOS. Capture and transcribe audio from your microphone, system audio, or any application. Includes a web UI and a headless Zoom bot for automatic meeting transcription.

## Prerequisites

- macOS (tested on macOS 10.15+)
- Python 3.10+
- [uv](https://docs.astral.sh/uv/): `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`
- System dependencies:
  ```bash
  brew install ffmpeg portaudio blackhole-2ch
  ```

### BlackHole Setup

BlackHole routes audio between applications. To capture system audio (Zoom, YouTube, etc.):

1. Open **Audio MIDI Setup** (Applications > Utilities)
2. Click **+** > Create **Multi-Output Device**
3. Check **BlackHole 2ch** and your speakers/headphones
4. Set the Multi-Output Device as your system output

See [BlackHole docs](https://github.com/ExistentialAudio/BlackHole) for more details.

## Installation

```bash
git clone <repository-url>
cd meeting-summarizer
make setup                # creates .venv with uv
source .venv/bin/activate
make install              # production deps
make install-dev          # dev deps + pre-commit hooks (optional)
```

Optionally copy `.env.example` to `.env` to customize settings (model size, compute type, etc.).

## Usage

### CLI

```bash
make run                  # record + transcribe live audio
# or: uv run python transcribe_live.py

# Transcribe an existing audio file
uv run python transcribe_live.py --transcribe-audio path/to/audio.wav

# Summarize a transcript
uv run python transcribe_live.py --summarize transcripts/transcript_*.txt

# Chat with a transcript
uv run python transcribe_live.py --chat transcripts/transcript_*.txt
```

### Web UI

```bash
make run-web              # starts FastAPI server at http://127.0.0.1:8000
```

### Zoom Bot

```bash
make install-playwright   # one-time browser install

# Join a meeting (headed mode, runs until Ctrl+C)
make run-audio-test URL="https://zoom.us/j/123" HEADED=1

# With a time limit
make run-audio-test URL="https://zoom.us/j/123" HEADED=1 DURATION=60

# Join a specific breakout room
make run-breakout-test URL="https://zoom.us/j/123" ROOM="Room 1"
```

## Development

```bash
make format               # ruff format + autofix
make lint                 # ruff check
make type-check           # mypy
make test                 # pytest with coverage
make audit                # pip-audit
make clean                # remove caches and build artifacts
```

## Configuration

Settings are controlled via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| WHISPER_MODEL | large-v3 | tiny / base / small / medium / large-v3 |
| DEVICE | cpu | cpu / cuda |
| COMPUTE_TYPE | int8 | int8 / float16 / float32 |
| OUTPUT_DIR | transcripts | Where recordings and transcripts are saved |
| AWS_REGION | us-east-1 | AWS region for Bedrock summarization |
| BEDROCK_MODEL_ID | (see .env.example) | Claude model for summarization/chat |

Zoom bot settings: `PLAYWRIGHT_HEADLESS`, `PLAYWRIGHT_TIMEOUT`, `PLAYWRIGHT_DEBUG` (see `.env.example`).

## License

(To be determined)
