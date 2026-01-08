# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Live Audio Transcription is a Python application for real-time audio transcription using faster-whisper and BlackHole on macOS. The project focuses on simplicity with a single-script architecture.

## Architecture

This is a **single-script application** with no module structure:

- **transcribe_live.py** - Main script containing all functionality:
  - Audio device detection and selection
  - Audio stream capture using PyAudio
  - Real-time transcription using faster-whisper
  - Console output formatting
  - Graceful shutdown handling

### Key Components

The script is organized into these main functions:

1. **list_audio_devices()** - Enumerate and display available audio input devices
2. **select_input_device()** - Auto-detect BlackHole or prompt user selection
3. **load_whisper_model()** - Initialize faster-whisper with configuration
4. **transcribe_audio_buffer()** - Process audio chunks and return transcribed text
5. **main()** - Orchestrate the transcription loop

### Data Flow

```
Audio Source (Microphone/System Audio)
  ↓
BlackHole Virtual Audio Device
  ↓
PyAudio Stream (16kHz, Mono)
  ↓
Audio Buffer (30-second chunks)
  ↓
faster-whisper Model
  ↓
Transcribed Text → Console Output
```

### Directory Structure

```
meeting-summarizer/
├── transcribe_live.py      # Main script (~250 lines)
├── requirements.txt         # Python dependencies
├── requirements-dev.txt     # Development dependencies
├── .env.example            # Configuration template
├── README.md               # User documentation
├── CLAUDE.md               # This file (developer guidance)
├── pyproject.toml          # Project metadata
├── Makefile                # Development commands
└── venv/                   # Virtual environment (local)
```

## Development Commands

### Initial Setup

```bash
# Create and activate virtual environment
make setup  # or: python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Install development dependencies
make install-dev  # or: pip install -r requirements-dev.txt

# Copy environment template (optional)
cp .env.example .env
# Edit .env to customize Whisper model, device, etc.
```

### System Dependencies

**Required before running:**
```bash
# macOS
brew install ffmpeg portaudio blackhole-2ch
```

### Running the Application

```bash
# Activate virtual environment
source venv/bin/activate

# Run the script
python transcribe_live.py

# With custom model size
WHISPER_MODEL=small python transcribe_live.py
```

### Code Quality

```bash
# Format code with ruff
make format  # or: python3 -m ruff format .

# Lint and auto-fix issues
python3 -m ruff check --fix .

# Lint without fixing
make lint  # or: python3 -m ruff check .

# Type checking with mypy
make type-check  # or: python3 -m mypy transcribe_live.py
```

## Implementation Guidelines

### Code Style

This is a single-script application, so keep it focused and maintainable:

- **Keep functions small** - Each function should do one thing well
- **Use clear names** - Function and variable names should be self-documenting
- **Add docstrings** - Brief docstrings for each function explaining purpose
- **Handle errors gracefully** - User-friendly error messages with troubleshooting hints
- **Console output matters** - Use emojis and formatting for clear UX

### Extending the Script

When adding features, consider:

1. **Adding command-line arguments** - Use `argparse` for flags like `--save`, `--model`, `--device`
2. **Adding new output formats** - Keep console output, add optional file saving
3. **Improving audio processing** - VAD tuning, better buffering strategies
4. **Cross-platform support** - Abstract audio device selection for Windows/Linux

**Do NOT**:
- Create separate modules unless absolutely necessary
- Add complex abstractions for a simple script
- Over-engineer with classes when functions suffice

### External Dependencies

**Core dependencies** (requirements.txt):
- **faster-whisper** - Optimized Whisper implementation using CTranslate2
- **pyaudio** - Audio I/O for capturing audio streams
- **python-dotenv** - Environment variable management (.env file)
- **numpy** - Audio data manipulation

**Development dependencies** (requirements-dev.txt):
- **ruff** - Fast Python linter and formatter
- **mypy** - Static type checking

**System dependencies** (must be installed separately):
- **ffmpeg** - Audio/video format conversion (required by faster-whisper)
  - macOS: `brew install ffmpeg`
  - Linux: `apt-get install ffmpeg`
- **portaudio** - Audio I/O library (required by pyaudio)
  - macOS: `brew install portaudio`
  - Linux: `apt-get install portaudio19-dev`
- **BlackHole** - Virtual audio driver for macOS
  - macOS: `brew install blackhole-2ch`

### Configuration

The script uses environment variables for configuration:

- **WHISPER_MODEL** - Model size (tiny, base, small, medium, large-v2, large-v3)
- **DEVICE** - Compute device (cpu, cuda)
- **COMPUTE_TYPE** - Quantization type (int8, float16, float32)
- **CHUNK_DURATION** - Audio buffer size in seconds

Configuration is loaded via:
1. `.env` file (if present)
2. System environment variables
3. Defaults (base model, cpu, int8, 30 seconds)

### Type Hints

All code uses Python type hints:
- Use `-> None` for functions with no return value
- Use `Optional[T]` for nullable types
- Use `List[T]`, `Dict[K, V]` for collections
- Enable strict mypy checking (configured in pyproject.toml)

### Error Handling

The script handles several error scenarios:

1. **Missing dependencies** - Clear install instructions
2. **Model download failures** - Check internet, suggest smaller models
3. **Audio device not found** - List available devices, suggest BlackHole install
4. **Audio buffer overflow** - Graceful degradation with warning
5. **Transcription errors** - Continue running, log error

All errors should:
- Print clear error messages with emoji indicators (❌, ⚠️)
- Provide actionable troubleshooting steps
- Exit cleanly or continue gracefully

### Performance Considerations

**Model Selection**:
- Default to `base` model (good balance of speed/accuracy)
- Recommend `tiny` for older hardware
- Suggest `medium` or `large` for high accuracy needs

**Audio Buffering**:
- 30-second chunks balance latency vs. accuracy
- Smaller chunks (10-15s) = lower latency, may cut off sentences
- Larger chunks (60s+) = better context, higher latency

**Voice Activity Detection (VAD)**:
- Enabled by default in faster-whisper
- Skips transcription of silence
- Improves performance and reduces unnecessary output

## Future Enhancement Ideas

Potential features to add (not currently implemented):

### Easy Additions:
- **Save to file** - Add `--save` flag to write transcripts with timestamps
- **Custom device selection** - Add `--device-id` flag to skip interactive selection
- **Model preloading** - Add `--preload` to load model before starting recording

### Medium Complexity:
- **Speaker diarization** - Integrate pyannote.audio to identify speakers
- **Real-time streaming** - Reduce buffer size, use streaming API
- **Multiple languages** - Language detection and selection

### Advanced:
- **Web interface** - Flask/FastAPI server with WebSocket for remote access
- **Translation** - Real-time translation of transcribed text
- **Windows/Linux support** - Abstract audio routing for other platforms

## Testing Strategy

Currently: **Manual testing only**

To test the script:
1. Run with various model sizes (tiny, base, small)
2. Test with microphone input (via BlackHole)
3. Test with system audio (Zoom, YouTube, etc.)
4. Test graceful shutdown (Ctrl+C)
5. Test error scenarios (missing dependencies, wrong device)

If adding automated tests:
- Use `pytest` (already in dev dependencies)
- Mock PyAudio for unit tests
- Test model loading, device selection, buffer handling
- Integration tests require real audio (may need fixtures)

## Troubleshooting Common Issues

### Development Issues

**Import errors after modifying script**:
- Restart Python interpreter
- Check for syntax errors with `python3 -m py_compile transcribe_live.py`

**Type checking fails**:
- Check pyproject.toml mypy configuration
- Verify type hints are correct
- Use `# type: ignore` sparingly for third-party library issues

**Linting errors**:
- Run `ruff format .` to auto-fix formatting
- Run `ruff check --fix .` to fix auto-fixable issues
- Review remaining issues manually

### Runtime Issues

**"No module named 'pyaudio'"**:
- Activate virtual environment: `source venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`

**"Model download fails"**:
- Check internet connection
- Check disk space (~150MB for base model)
- Models cache to `~/.cache/huggingface/hub/`

**"No BlackHole device found"**:
- Install BlackHole: `brew install blackhole-2ch`
- Restart script and manually select device

## Git Workflow

Since this is a simple single-script project:

1. Make changes to `transcribe_live.py`
2. Test manually
3. Format: `make format`
4. Lint: `make lint`
5. Type check: `make type-check`
6. Commit with clear message
7. Push to remote

Keep commits atomic and focused on single features or fixes.
