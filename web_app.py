#!/usr/bin/env python3
"""
Web UI for live audio transcription.

Provides a browser-based interface for real-time transcription with:
- Start/stop controls
- Audio level meter
- Live transcript display
"""

import asyncio
import json
import os
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from queue import Empty, Queue
from typing import Any

import boto3
import numpy as np
import pyaudio
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel

# Load environment variables
load_dotenv()

# Configuration (reuse from transcribe_live.py settings)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
DEVICE = os.getenv("DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
CHUNK_DURATION = int(os.getenv("CHUNK_DURATION", "60"))

# AWS Bedrock Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")

# Output directory for transcripts
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "transcripts")

# Audio settings
RATE = 16000  # Sample rate in Hz (Whisper uses 16kHz)
CHANNELS = 1  # Mono audio
CHUNK = 1024  # Buffer size
FORMAT = pyaudio.paInt16  # 16-bit audio

# Level update interval
LEVEL_UPDATE_INTERVAL = 0.1  # 100ms


class TranscriptionState:
    """Thread-safe state for transcription session."""

    def __init__(self) -> None:
        self.running = False
        self.model: WhisperModel | None = None
        self.device_name: str = ""
        self.start_time: datetime | None = None
        self.worker_thread: threading.Thread | None = None
        self.transcript_segments: list[dict[str, str]] = []
        self.chat_history: list[dict[str, str]] = []
        self.transcript_file: Any = None
        self.transcript_path: str = ""
        self._lock = threading.Lock()

    def start(self, device_name: str) -> None:
        with self._lock:
            self.running = True
            self.device_name = device_name
            self.start_time = datetime.now()
            self.transcript_segments = []
            self.chat_history = []
            # Create transcript file
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            timestamp = self.start_time.strftime("%Y-%m-%d_%H-%M-%S")
            self.transcript_path = os.path.join(OUTPUT_DIR, f"transcript_{timestamp}.txt")
            self.transcript_file = open(self.transcript_path, "w", encoding="utf-8")
            self.transcript_file.write(f"Transcript started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.transcript_file.write(f"Audio device: {device_name}\n")
            self.transcript_file.write(f"Model: {WHISPER_MODEL}\n")
            self.transcript_file.write("\n")
            self.transcript_file.flush()

    def stop(self) -> None:
        with self._lock:
            self.running = False
            # Close transcript file with footer
            if self.transcript_file:
                end_time = datetime.now()
                self.transcript_file.write("\n---\n")
                self.transcript_file.write(f"Transcript ended: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                if self.start_time:
                    elapsed = end_time - self.start_time
                    total_seconds = int(elapsed.total_seconds())
                    hours, remainder = divmod(total_seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    if hours > 0:
                        duration = f"{hours}:{minutes:02d}:{seconds:02d}"
                    else:
                        duration = f"{minutes}:{seconds:02d}"
                    self.transcript_file.write(f"Duration: {duration}\n")
                self.transcript_file.close()
                self.transcript_file = None

    def is_running(self) -> bool:
        with self._lock:
            return self.running

    def add_transcript(self, timestamp: str, text: str) -> None:
        with self._lock:
            self.transcript_segments.append({"timestamp": timestamp, "text": text})
            # Write to file
            if self.transcript_file:
                self.transcript_file.write(f"{timestamp} {text}\n")
                self.transcript_file.flush()

    def get_transcript_text(self) -> str:
        with self._lock:
            return "\n".join(
                f"{seg['timestamp']} {seg['text']}" for seg in self.transcript_segments
            )

    def load_transcript_file(self, filepath: str) -> bool:
        """Load a transcript from a file."""
        if not os.path.exists(filepath):
            return False

        with self._lock:
            self.transcript_segments = []
            self.chat_history = []
            self.loaded_file = filepath

            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            # Parse transcript lines (lines starting with timestamps like [00:01:30])
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("[") and "]" in line:
                    bracket_end = line.index("]")
                    timestamp = line[: bracket_end + 1]
                    text = line[bracket_end + 1 :].strip()
                    if text:
                        self.transcript_segments.append(
                            {"timestamp": timestamp, "text": text}
                        )

            return len(self.transcript_segments) > 0

    def clear_loaded_transcript(self) -> None:
        """Clear the loaded transcript."""
        with self._lock:
            self.transcript_segments = []
            self.chat_history = []
            self.loaded_file = ""

    def clear_chat_history(self) -> None:
        with self._lock:
            self.chat_history = []

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            elapsed = 0
            if self.start_time and self.running:
                elapsed = int((datetime.now() - self.start_time).total_seconds())
            loaded_file = getattr(self, "loaded_file", "")
            return {
                "running": self.running,
                "device": self.device_name,
                "elapsed_seconds": elapsed,
                "has_transcript": len(self.transcript_segments) > 0,
                "loaded_file": os.path.basename(loaded_file) if loaded_file else None,
            }


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        disconnected: set[WebSocket] = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        self.active_connections -= disconnected


# Global state
state = TranscriptionState()
manager = ConnectionManager()
level_queue: Queue[float] = Queue()
transcript_queue: Queue[dict[str, Any]] = Queue()


def get_audio_devices() -> list[dict[str, Any]]:
    """Get list of available audio devices (input and aggregate)."""
    p = pyaudio.PyAudio()
    devices = []

    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        input_channels = int(info["maxInputChannels"])
        output_channels = int(info["maxOutputChannels"])
        name = str(info["name"])

        # Show devices that have input OR are aggregate/multi-output devices
        # Aggregate devices often have both input and output, or may show as output-only
        is_aggregate = "aggregate" in name.lower() or "multi" in name.lower()
        is_blackhole = "BlackHole" in name
        has_input = input_channels > 0

        if has_input or is_aggregate or is_blackhole:
            devices.append(
                {
                    "index": i,
                    "name": name,
                    "input_channels": input_channels,
                    "output_channels": output_channels,
                    "is_blackhole": is_blackhole,
                    "is_aggregate": is_aggregate,
                    "has_input": has_input,
                }
            )

    p.terminate()
    return devices


def load_model() -> WhisperModel:
    """Load Whisper model (cached)."""
    if state.model is None:
        state.model = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type=COMPUTE_TYPE)
    return state.model


def transcribe_audio_buffer(model: WhisperModel, audio_data: np.ndarray) -> str | None:
    """Transcribe an audio buffer using Whisper."""
    try:
        audio_float = audio_data.astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio_float,
            language=None,
            vad_filter=True,
            beam_size=5,
        )
        text = " ".join([segment.text.strip() for segment in segments])
        return text if text.strip() else None
    except Exception:
        return None


def format_elapsed_time(start_time: datetime) -> str:
    """Format elapsed time as [HH:MM:SS]."""
    elapsed = datetime.now() - start_time
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"


def audio_worker(device_idx: int) -> None:
    """Background worker for audio capture and transcription."""
    model = load_model()
    p = pyaudio.PyAudio()

    try:
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=device_idx,
            frames_per_buffer=CHUNK,
        )

        chunks_per_buffer = int(RATE / CHUNK * CHUNK_DURATION)
        audio_buffer: list[np.ndarray] = []
        chunk_count = 0
        last_level_time = 0.0

        while state.is_running():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_chunk = np.frombuffer(data, dtype=np.int16)
                audio_buffer.append(audio_chunk)
                chunk_count += 1

                # Send level updates (throttled)
                current_time = time.time()
                if current_time - last_level_time >= LEVEL_UPDATE_INTERVAL:
                    level = float(np.abs(audio_chunk).mean())
                    level_queue.put(level)
                    last_level_time = current_time

                # Process buffer when full
                if chunk_count >= chunks_per_buffer:
                    audio_data = np.concatenate(audio_buffer)
                    avg_level = np.abs(audio_data).mean()

                    if avg_level > 10:  # Not silence
                        text = transcribe_audio_buffer(model, audio_data)
                        if text and state.start_time:
                            timestamp = format_elapsed_time(state.start_time)
                            elapsed = int((datetime.now() - state.start_time).total_seconds())
                            # Store transcript for chat context
                            state.add_transcript(timestamp, text)
                            transcript_queue.put(
                                {
                                    "text": text,
                                    "timestamp": timestamp,
                                    "elapsed_seconds": elapsed,
                                }
                            )

                    audio_buffer = []
                    chunk_count = 0

            except Exception:
                continue

        stream.stop_stream()
        stream.close()

    finally:
        p.terminate()


async def broadcast_worker() -> None:
    """Async worker to broadcast queue contents to WebSocket clients."""
    loop = asyncio.get_event_loop()

    while True:
        # Check level queue
        try:
            level = await loop.run_in_executor(None, lambda: level_queue.get_nowait())
            await manager.broadcast({"type": "level", "value": level})
        except Empty:
            pass

        # Check transcript queue
        try:
            transcript = await loop.run_in_executor(None, lambda: transcript_queue.get_nowait())
            await manager.broadcast({"type": "transcript", **transcript})
        except Empty:
            pass

        await asyncio.sleep(0.05)  # 50ms polling interval


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown events."""
    # Start broadcast worker
    task = asyncio.create_task(broadcast_worker())
    yield
    # Cleanup
    task.cancel()
    state.stop()


app = FastAPI(title="Live Transcription", lifespan=lifespan)

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root() -> FileResponse:
    """Serve the main UI."""
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/api/devices")
async def get_devices() -> list[dict[str, Any]]:
    """List available audio input devices."""
    return get_audio_devices()


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    """Get current transcription status."""
    return state.get_status()


@app.post("/api/start")
async def start_transcription(body: dict[str, Any]) -> JSONResponse:
    """Start transcription with specified device."""
    if state.is_running():
        return JSONResponse(
            status_code=400, content={"error": "Transcription already running"}
        )

    device_idx = body.get("device_id")
    if device_idx is None:
        return JSONResponse(status_code=400, content={"error": "device_id required"})

    # Get device name
    devices = get_audio_devices()
    device = next((d for d in devices if d["index"] == device_idx), None)
    if not device:
        return JSONResponse(status_code=400, content={"error": "Invalid device_id"})

    # Start transcription
    state.start(device["name"])

    # Spawn worker thread
    state.worker_thread = threading.Thread(target=audio_worker, args=(device_idx,), daemon=True)
    state.worker_thread.start()

    # Broadcast status
    await manager.broadcast({"type": "status", **state.get_status()})

    return JSONResponse(content={"status": "started", "device": device["name"]})


@app.post("/api/stop")
async def stop_transcription() -> JSONResponse:
    """Stop transcription."""
    if not state.is_running():
        return JSONResponse(
            status_code=400, content={"error": "Transcription not running"}
        )

    state.stop()

    # Wait for worker thread to finish
    if state.worker_thread:
        state.worker_thread.join(timeout=5.0)

    # Broadcast status
    await manager.broadcast({"type": "status", **state.get_status()})

    return JSONResponse(content={"status": "stopped"})


@app.get("/api/transcripts")
async def list_transcripts() -> list[dict[str, Any]]:
    """List available transcript files."""
    transcripts: list[dict[str, Any]] = []

    if not os.path.exists(OUTPUT_DIR):
        return transcripts

    for filename in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        if filename.startswith("transcript_") and filename.endswith(".txt"):
            filepath = os.path.join(OUTPUT_DIR, filename)
            stat = os.stat(filepath)
            # Parse date from filename: transcript_YYYY-MM-DD_HH-MM-SS.txt
            try:
                date_str = filename[11:-4]  # Remove "transcript_" and ".txt"
                # Format: 2026-01-09_11-21-25 -> 2026-01-09 11:21:25
                date_part = date_str[:10]  # 2026-01-09
                time_part = date_str[11:].replace("-", ":")  # 11:21:25
                date_str = f"{date_part} {time_part}"
            except Exception:
                date_str = ""

            transcripts.append(
                {
                    "filename": filename,
                    "size": stat.st_size,
                    "date": date_str,
                }
            )

    return transcripts


@app.post("/api/transcripts/load")
async def load_transcript(body: dict[str, Any]) -> JSONResponse:
    """Load a transcript file for chat."""
    filename = body.get("filename", "")
    if not filename:
        return JSONResponse(status_code=400, content={"error": "filename required"})

    # Security: Only allow loading from OUTPUT_DIR
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})

    filepath = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(filepath):
        return JSONResponse(status_code=404, content={"error": "File not found"})

    if state.load_transcript_file(filepath):
        # Broadcast status update
        await manager.broadcast({"type": "status", **state.get_status()})
        return JSONResponse(
            content={
                "status": "loaded",
                "filename": filename,
                "segments": len(state.transcript_segments),
            }
        )
    else:
        return JSONResponse(
            status_code=400, content={"error": "No transcript content found in file"}
        )


@app.post("/api/transcripts/unload")
async def unload_transcript() -> JSONResponse:
    """Unload the current transcript."""
    state.clear_loaded_transcript()
    await manager.broadcast({"type": "status", **state.get_status()})
    return JSONResponse(content={"status": "unloaded"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)

    # Send current status on connect
    await websocket.send_json({"type": "status", **state.get_status()})

    try:
        while True:
            # Keep connection alive, handle client messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/chat")
async def chat_with_transcript(body: dict[str, Any]) -> JSONResponse:
    """Chat with the transcript using AWS Bedrock."""
    message = body.get("message", "").strip()
    if not message:
        return JSONResponse(status_code=400, content={"error": "message required"})

    transcript_text = state.get_transcript_text()
    if not transcript_text:
        return JSONResponse(
            status_code=400,
            content={"error": "No transcript available. Load a transcript or start recording."},
        )

    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        # Build system prompt with transcript context
        system_prompt = f"""You are a helpful assistant that answers questions about a meeting transcript.
You have access to the transcript below. Answer questions accurately based on what was discussed.
If something wasn't mentioned in the meeting, say so.
Keep responses concise and helpful.

=== MEETING TRANSCRIPT ===
{transcript_text}
=== END TRANSCRIPT ==="""

        # Add user message to history
        state.chat_history.append({"role": "user", "content": message})

        # Call Bedrock
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": state.chat_history,
                }
            ),
        )

        result = json.loads(response["body"].read())
        assistant_message = result["content"][0]["text"]

        # Add assistant response to history
        state.chat_history.append({"role": "assistant", "content": assistant_message})

        return JSONResponse(content={"response": assistant_message})

    except Exception as e:
        # Remove failed user message from history
        if state.chat_history and state.chat_history[-1]["role"] == "user":
            state.chat_history.pop()
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/chat/clear")
async def clear_chat() -> JSONResponse:
    """Clear chat history."""
    state.clear_chat_history()
    return JSONResponse(content={"status": "cleared"})
