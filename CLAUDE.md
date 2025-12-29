# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Meeting Summarizer is a Python application for processing audio recordings, transcribing them, and generating summaries. The project is designed with a modular architecture separating concerns across multiple domains.

## Architecture

The codebase is organized into five main modules under `src/`:

- **audio**: Audio processing, recording, and manipulation functionality
- **transcription**: Speech-to-text conversion using transcription services
- **summarization**: AI-powered summarization of transcripts
- **storage**: Data persistence layer for audio files, transcripts, and summaries
- **gui**: User interface components

### Data Flow

1. Audio files are processed via the `audio` module
2. The `transcription` module converts audio to text
3. Transcripts are passed to the `summarization` module for analysis
4. The `storage` module handles persistence of all artifacts
5. The `gui` module provides user interaction

### Directory Structure

- `src/` - Source code organized by domain
- `tests/` - Test suite mirroring the source structure
- `data/` - Runtime data directory
  - `data/audio/` - Audio file storage
  - `data/transcripts/` - Transcript storage
- `examples/` - Example scripts and usage demonstrations

## Development Commands

### Initial Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -r requirements-dev.txt

# Or install as editable package with dev dependencies
pip install -e ".[dev]"

# Copy environment template and add your API keys
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY and ANTHROPIC_API_KEY
```

### Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_storage.py

# Run tests with coverage report
pytest --cov=src --cov-report=html

# Run tests and generate coverage in terminal
pytest --cov=src --cov-report=term-missing

# Run specific test by name
pytest tests/test_storage.py::test_save_audio -v
```

### Code Quality

```bash
# Format code with ruff
ruff format .

# Lint and auto-fix issues
ruff check --fix .

# Lint without fixing
ruff check .

# Type checking with mypy
mypy src/

# Format with black (alternative)
black src/ tests/
```

### Running Individual Modules

```bash
# Import and use modules in Python
python -c "from src.storage.manager import StorageManager; print(StorageManager)"
```

## Implementation Guidelines

### Module Boundaries

Each module under `src/` should maintain clear boundaries:
- The `storage` module is the only module that directly interacts with the filesystem for data persistence
- The `transcription` and `summarization` modules should be agnostic to storage implementation
- The `gui` module orchestrates calls to other modules but contains no business logic

### External Dependencies

Current dependencies (see pyproject.toml and requirements.txt):
- **anthropic** - Claude API client for AI summarization
- **openai** - OpenAI API client for Whisper transcription
- **pydub** - Audio file manipulation and format conversion
- **python-dotenv** - Environment variable management

Development dependencies:
- **pytest** - Testing framework
- **pytest-cov** - Coverage reporting
- **ruff** - Fast Python linter and formatter (replaces black, flake8, isort)
- **mypy** - Static type checking
- **black** - Code formatter (backup option)

### Design Patterns

- **Protocol-based dependency injection**: Services use Protocol types for providers, enabling easy mocking and implementation swapping
- **Service layer pattern**: Business logic separated into service classes (TranscriptionService, SummarizationService)
- **Repository pattern**: StorageManager handles all data persistence
- **Clear module boundaries**: Each module has a single responsibility and minimal coupling

### Type Hints

All code uses Python type hints. When adding new code:
- Use `from typing import Protocol` for interfaces
- Use `Path` from pathlib instead of strings for file paths
- Use `-> None` for functions with no return value
- Enable strict mypy checking (already configured in pyproject.toml)
