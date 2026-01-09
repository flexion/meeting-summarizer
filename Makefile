.PHONY: help setup install install-dev check-system-deps run run-web lint format type-check clean

help:
	@echo "Live Audio Transcription - Development Commands"
	@echo ""
	@echo "make setup             - Create virtual environment"
	@echo "make install           - Install production dependencies"
	@echo "make install-dev       - Install development dependencies"
	@echo "make check-system-deps - Check for required system dependencies"
	@echo "make run               - Run the transcription script (CLI)"
	@echo "make run-web           - Run the web UI server"
	@echo "make lint              - Run linter"
	@echo "make format            - Format code"
	@echo "make type-check        - Run type checker"
	@echo "make clean             - Clean up generated files"

setup:
	python3 -m venv venv
	@echo ""
	@echo "Virtual environment created. Activate it with:"
	@echo "  source venv/bin/activate"
	@echo ""
	@echo "Then install dependencies:"
	@echo "  make install"

install:
	python3 -m pip install -r requirements.txt
	@echo ""
	@echo "Dependencies installed!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Check system dependencies: make check-system-deps"
	@echo "  2. Run the script: make run (or python transcribe_live.py)"

install-dev:
	python3 -m pip install -r requirements-dev.txt
	@echo ""
	@echo "Development dependencies installed!"

check-system-deps:
	@echo "Checking system dependencies..."
	@echo ""
	@command -v ffmpeg >/dev/null 2>&1 && echo "✓ ffmpeg found" || echo "✗ ffmpeg NOT found - install with: brew install ffmpeg"
	@command -v python3 >/dev/null 2>&1 && echo "✓ python3 found" || echo "✗ python3 NOT found"
	@echo ""
	@echo "Checking macOS-specific dependencies:"
	@if brew list portaudio &>/dev/null; then echo "✓ portaudio found"; else echo "✗ portaudio NOT found - install with: brew install portaudio"; fi
	@if brew list blackhole-2ch &>/dev/null; then echo "✓ BlackHole found"; else echo "✗ BlackHole NOT found - install with: brew install blackhole-2ch"; fi
	@echo ""
	@echo "All dependencies installed? Run: make run"

run:
	python3 transcribe_live.py

run-web:
	python3 -m uvicorn web_app:app --reload --host 127.0.0.1 --port 8000

lint:
	python3 -m ruff check .

format:
	python3 -m ruff format .
	python3 -m ruff check --fix .

type-check:
	python3 -m mypy transcribe_live.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name .coverage -delete 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info/ 2>/dev/null || true
