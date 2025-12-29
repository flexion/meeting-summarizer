# Meeting Summarizer

AI-powered meeting transcription and summarization tool that converts audio recordings into structured text transcripts and generates concise summaries.

## Features

- Audio recording and processing
- Automatic speech-to-text transcription
- AI-powered meeting summarization
- Local storage for audio files and transcripts
- GUI interface for easy interaction

## Architecture

The project is organized into modular components:

- `src/audio/` - Audio capture and processing
- `src/transcription/` - Speech-to-text conversion
- `src/summarization/` - AI-powered text summarization
- `src/storage/` - Data persistence layer
- `src/gui/` - User interface

## Installation

### Prerequisites

- Python 3.10 or higher
- pip package manager

### Quick Start with Makefile

```bash
# 1. Create virtual environment
make setup

# 2. Activate it
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install development dependencies
make install-dev

# 4. Copy and configure environment variables
cp .env.example .env
# Edit .env and add your API keys
```

### Manual Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd meeting-summarizer
```

2. Create and activate virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
# For development
python3 -m pip install -r requirements-dev.txt

# Or as editable package
python3 -m pip install -e ".[dev]"
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env and add your API keys:
# OPENAI_API_KEY=your_openai_key_here
# ANTHROPIC_API_KEY=your_anthropic_key_here
```

## Development

### Using Makefile Commands

```bash
make test          # Run all tests
make coverage      # Run tests with coverage report
make lint          # Check code quality
make format        # Auto-format code
make type-check    # Run type checker
make clean         # Clean up generated files
```

### Running Tests Manually

```bash
# Run all tests
python3 -m pytest

# Run with coverage
python3 -m pytest --cov=src --cov-report=html

# Run specific test file
python3 -m pytest tests/test_storage.py
```

### Code Quality

```bash
# Format code with ruff
python3 -m ruff format .

# Lint code
python3 -m ruff check .

# Fix auto-fixable issues
python3 -m ruff check --fix .

# Type checking
python3 -m mypy src/
```

### Project Structure

```
meeting-summarizer/
├── src/
│   ├── audio/          # Audio processing
│   ├── gui/            # User interface
│   ├── storage/        # Data persistence
│   ├── summarization/  # AI summarization
│   └── transcription/  # Speech-to-text
├── tests/              # Test suite
├── data/               # Runtime data
│   ├── audio/          # Audio files
│   └── transcripts/    # Transcript files
└── examples/           # Example scripts

```

## Usage

(To be added as the application develops)

## License

(To be determined)
