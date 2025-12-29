.PHONY: help setup install install-dev test coverage lint format type-check clean

help:
	@echo "Meeting Summarizer - Development Commands"
	@echo ""
	@echo "make setup         - Create virtual environment"
	@echo "make install       - Install production dependencies"
	@echo "make install-dev   - Install development dependencies"
	@echo "make test          - Run tests"
	@echo "make coverage      - Run tests with coverage report"
	@echo "make lint          - Run linter"
	@echo "make format        - Format code"
	@echo "make type-check    - Run type checker"
	@echo "make clean         - Clean up generated files"

setup:
	python3 -m venv venv
	@echo ""
	@echo "Virtual environment created. Activate it with:"
	@echo "  source venv/bin/activate"

install:
	python3 -m pip install -r requirements.txt

install-dev:
	python3 -m pip install -r requirements-dev.txt

test:
	python3 -m pytest

coverage:
	python3 -m pytest --cov=src --cov-report=html --cov-report=term-missing

lint:
	python3 -m ruff check .

format:
	python3 -m ruff format .
	python3 -m ruff check --fix .

type-check:
	python3 -m mypy src/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name .coverage -delete 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info/ 2>/dev/null || true
