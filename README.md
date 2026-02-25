# Live Audio Transcription

Real-time audio transcription using faster-whisper and BlackHole for macOS. Capture and transcribe audio from your microphone, system audio, or any application in real-time. Includes a headless Zoom bot for automatic meeting and breakout room transcription.

## Features

- 🎙️ **Live transcription** - Real-time audio-to-text conversion
- ⚡ **Fast & efficient** - Uses faster-whisper (4x faster than openai-whisper)
- 🎯 **Voice Activity Detection** - Only transcribes when speech is detected
- 🖥️ **Console output** - Simple, clean terminal interface
- 🔧 **Configurable** - Multiple Whisper model sizes and settings
- 🍎 **macOS optimized** - Uses BlackHole for audio routing
- 🤖 **Zoom Bot** - Headless browser bot for automatic meeting transcription
- 📍 **Breakout Rooms** - Auto-join and transcribe Zoom breakout rooms

## Prerequisites

### System Requirements
- macOS (tested on macOS 10.15+)
- Python 3.10 or higher
- Homebrew (for installing system dependencies)

### System Dependencies

You need to install two system packages:

```bash
# Install FFmpeg (audio processing)
brew install ffmpeg

# Install PortAudio (audio I/O)
brew install portaudio

# Install BlackHole (virtual audio device)
brew install blackhole-2ch
```

### BlackHole Setup

BlackHole creates a virtual audio device that routes audio between applications. After installation, you need to configure it:

#### Option 1: Capture Microphone Audio
1. Open **System Settings → Sound**
2. Set **Input** to your microphone
3. Run the script and select the BlackHole device when prompted

#### Option 2: Capture System Audio (Zoom, YouTube, etc.)
1. Open **Audio MIDI Setup** (Applications → Utilities)
2. Click the **+** button → Create **Multi-Output Device**
3. Check **BlackHole 2ch** and your speakers/headphones
4. Set this Multi-Output Device as your system output
5. In the script, select BlackHole as input

For detailed instructions, see [BlackHole documentation](https://github.com/ExistentialAudio/BlackHole).

## Installation

1. **Clone the repository:**
```bash
git clone <repository-url>
cd meeting-summarizer
```

2. **Create and activate virtual environment:**
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

4. **(Optional) Configure settings:**
```bash
cp .env.example .env
# Edit .env to customize model size, device, etc.
```

## Usage

### Basic Usage

Simply run the script:

```bash
python transcribe_live.py
```

The script will:
1. List all available audio devices
2. Auto-detect and select BlackHole (or let you choose manually)
3. Load the Whisper model (downloads on first run)
4. Start transcribing!

### Stop Transcription

Press **Ctrl+C** to stop gracefully.

### Example Session

```
🎙️  Live Audio Transcription with faster-whisper
============================================================

🎤 Available Audio Devices:
------------------------------------------------------------
  [0] MacBook Pro Microphone
    Input channels: 1
    Output channels: 0

➜ [1] BlackHole 2ch
    Input channels: 2
    Output channels: 0
    ⭐ BlackHole device detected!

✅ Auto-selected BlackHole device: [1] BlackHole 2ch

Use this device? (Y/n): y

📥 Loading Whisper model: base
   Device: cpu
   Compute type: int8
✅ Model loaded successfully!

============================================================
🎤 Recording started! Speak or play audio...
⏱️  Buffer duration: 30 seconds
🛑 Press Ctrl+C to stop
============================================================

🔄 Transcribing...
💬 Hello, this is a test of the live transcription system.

🔄 Transcribing...
💬 It's working great so far!
```

## Zoom Web Bot

The Zoom web bot joins meetings via headless browser, captures audio, and can automatically navigate to breakout rooms.

### Prerequisites

Install Playwright browser:

```bash
make install-playwright
# or: playwright install chromium
```

### Basic Usage

Join a meeting and capture audio:

```bash
# Join meeting (headed mode, runs until Ctrl+C)
python playwright_bot/test_audio.py "https://zoom.us/j/123456789" --headed

# Join meeting with specific duration (60 seconds)
python playwright_bot/test_audio.py "https://zoom.us/j/123456789" --headed --duration 60

# With transcription after recording
python playwright_bot/test_audio.py "https://zoom.us/j/123456789" --transcribe
```

### Breakout Room Support

Join a specific breakout room (requires "Allow participants to choose room" enabled by host):

```bash
# Join meeting, wait for breakout rooms, then join "Room 1" (runs until Ctrl+C)
python playwright_bot/test_audio.py "https://zoom.us/j/123456789" --room "Room 1"

# List available breakout rooms only
python playwright_bot/test_breakout.py "https://zoom.us/j/123456789" --list-only
```

### Using Makefile

```bash
# Audio capture test (runs until Ctrl+C)
make run-audio-test URL="https://zoom.us/j/123456789"

# With headed mode
make run-audio-test URL="https://zoom.us/j/123456789" HEADED=1

# With specific duration (60 seconds)
make run-audio-test URL="https://zoom.us/j/123456789" HEADED=1 DURATION=60

# Breakout room test
make run-breakout-test URL="https://zoom.us/j/123456789" ROOM="Room 1"
```

### Bot Configuration

Environment variables for the Zoom bot:

| Variable | Default | Description |
|----------|---------|-------------|
| PLAYWRIGHT_HEADLESS | true | Run browser in headless mode |
| PLAYWRIGHT_TIMEOUT | 60000 | Default timeout in ms |
| PLAYWRIGHT_SLOWMO | 0 | Slow down actions (ms) for debugging |
| PLAYWRIGHT_DEBUG | false | Enable verbose logging |
| PLAYWRIGHT_SCREENSHOTS | true | Take screenshots on errors |

### Bot Features

- **Auto-join**: Handles pre-join screen, name entry, audio setup
- **Waiting room**: Waits for host admission (configurable timeout)
- **Breakout rooms**: Detects when rooms open, joins by name
- **Audio capture**: Captures meeting audio via Web Audio API
- **Meeting monitoring**: Detects meeting end, auto-saves audio
- **State machine**: Tracks bot state (IDLE → IN_MEETING → MEETING_ENDED)

### Output Files

Audio recordings saved to `transcripts/` directory:
- `recording_YYYY-MM-DD_HH-MM-SS.wav` - Audio (16kHz, mono, 16-bit PCM)
- `error_screenshot_*.png` - Screenshots on errors (if enabled)

For detailed technical documentation, see [docs/zoom-breakout-bot.md](docs/zoom-breakout-bot.md).

## Configuration

You can customize the transcription behavior by editing `.env` or setting environment variables:

### Model Size

Choose a model based on your accuracy vs. speed requirements:

```bash
WHISPER_MODEL=base  # Options: tiny, base, small, medium, large-v2, large-v3
```

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| tiny | ~75MB | Fastest | Lowest |
| base | ~150MB | Fast | Good (default) |
| small | ~500MB | Moderate | Better |
| medium | ~1.5GB | Slow | High |
| large-v2/v3 | ~3GB | Slowest | Best |

### Device & Compute Type

```bash
DEVICE=cpu          # Options: cpu, cuda (requires NVIDIA GPU)
COMPUTE_TYPE=int8   # Options: int8, float16, float32
```

**Recommendations:**
- CPU: Use `int8` (fastest, lowest memory)
- GPU (CUDA): Use `float16` (faster than float32)

### Buffer Duration

Adjust the audio chunk size (affects latency vs. accuracy):

```bash
CHUNK_DURATION=30  # Seconds (default: 30)
```

- **Smaller values** (10-15s): Lower latency, may cut off speech
- **Larger values** (30-60s): Better accuracy, higher latency

## Troubleshooting

### "No module named 'pyaudio'" or "No module named 'faster_whisper'"

Make sure you've installed the dependencies:
```bash
pip install -r requirements.txt
```

### "Error loading model"

The model downloads on first run. Check:
1. Internet connection (models download from Hugging Face)
2. Disk space (~150MB for base model)
3. Try a smaller model: `WHISPER_MODEL=tiny` in `.env`

### "No BlackHole device found"

Make sure BlackHole is installed:
```bash
brew install blackhole-2ch
```

Then restart the script and manually select the BlackHole device.

### "Input overflowed" error

This is usually harmless and means the audio buffer got full. The script continues working. If it happens frequently:
1. Increase buffer size in the code (CHUNK variable)
2. Close other audio applications
3. Restart your computer

### Poor transcription quality

1. Use a larger model: `WHISPER_MODEL=medium`
2. Increase buffer duration: `CHUNK_DURATION=60`
3. Check audio routing - ensure audio is actually reaching BlackHole
4. Test with higher volume

### No transcription output

1. Verify audio is reaching BlackHole:
   - Open **Audio MIDI Setup**
   - Select BlackHole device
   - Check the input level meters (should show activity)
2. Check volume levels (may be too quiet)
3. Try speaking louder or playing audio at higher volume

## Model Downloads

On first run, the script downloads the Whisper model:
- **Location**: `~/.cache/huggingface/hub/`
- **Size**: 75MB (tiny) to 3GB (large)
- **Time**: 1-5 minutes depending on connection

## Performance Notes

| Setup | Speed | Notes |
|-------|-------|-------|
| MacBook Pro (M1/M2/M3) + base | Fast | Recommended |
| MacBook Pro (Intel) + base | Moderate | Use tiny for faster processing |
| MacBook Air + tiny | Fast | Good for basic transcription |
| GPU (CUDA) + medium | Very fast | Best quality |

## Future Enhancements

Potential features (not currently implemented):
- Save transcripts to file with `--save` flag
- Speaker diarization (identify who's speaking)
- Real-time translation
- Windows/Linux support
- Web interface for remote transcription

## Development

### Code Quality

```bash
# Format code
python -m ruff format .

# Lint code
python -m ruff check .

# Type checking
python -m mypy transcribe_live.py
```

### Using Make Commands

```bash
make setup          # Create virtual environment
make install-dev    # Install dev dependencies
make format         # Format code with ruff
make lint           # Check code quality
```

## Technical Details

**Stack:**
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) - Optimized Whisper implementation using CTranslate2
- [PyAudio](https://people.csail.mit.edu/hubert/pyaudio/) - Audio I/O
- [BlackHole](https://github.com/ExistentialAudio/BlackHole) - Virtual audio driver for macOS

**Audio Pipeline:**
```
Audio Source → BlackHole → PyAudio Stream → 30s Buffer →
faster-whisper → Console Output
```

## License

(To be determined)
