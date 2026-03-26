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
import wave
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

from bedrock_utils import summarize_transcript
from playwright_bot.zoom_web_bot import BotConfig, BotState, ZoomWebBot

# Load environment variables
load_dotenv()

# Configuration (reuse from transcribe_live.py settings)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3-turbo")
DEVICE = os.getenv("DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")

# AWS Bedrock Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")

# Output directory for transcripts
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "transcripts")

# Auto-summarize configuration
AUTO_SUMMARIZE = os.getenv("AUTO_SUMMARIZE", "true").lower() == "true"


def _has_aws_credentials() -> bool:
    """Check if AWS credentials are available for Bedrock API calls."""
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None
    except Exception:
        return False


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
        self.transcribing = False  # True while processing audio after recording stops
        self.model: WhisperModel | None = None
        self.device_name: str = ""
        self.start_time: datetime | None = None
        self.end_time: datetime | None = None
        self.worker_thread: threading.Thread | None = None
        self.transcript_segments: list[dict[str, str]] = []
        self.chat_history: list[dict[str, str]] = []
        self.transcript_file: Any = None
        self.transcript_path: str = ""
        self.wav_path: str = ""
        self.wav_file: wave.Wave_write | None = None
        self.total_frames: int = 0
        self._lock = threading.Lock()
        # Summary state
        self.summary_text: str | None = None
        self.summary_status: str = "idle"  # "idle", "generating", "complete", "error"
        self.summary_error: str | None = None
        self.summary_transcript_text: str | None = None  # for Zoom bot path manual re-gen
        self._summary_task: asyncio.Task[None] | None = None  # reference to running summary task

    def start(self, device_name: str) -> None:
        with self._lock:
            self.running = True
            self.transcribing = False
            self.device_name = device_name
            self.start_time = datetime.now()
            self.end_time = None
            self.transcript_segments = []
            self.chat_history = []
            self.total_frames = 0

            # Cancel running summary if any
            if self._summary_task is not None and not self._summary_task.done():
                self._summary_task.cancel()
            self._summary_task = None
            self.summary_text = None
            self.summary_status = "idle"
            self.summary_error = None
            self.summary_transcript_text = None

            # Create output directory
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            timestamp = self.start_time.strftime("%Y-%m-%d_%H-%M-%S")

            # Create WAV file for recording
            self.wav_path = os.path.join(OUTPUT_DIR, f"recording_{timestamp}.wav")
            self.wav_file = wave.open(self.wav_path, "wb")
            self.wav_file.setnchannels(CHANNELS)
            self.wav_file.setsampwidth(2)  # 16-bit audio = 2 bytes
            self.wav_file.setframerate(RATE)

            # Set transcript path (will be written after transcription)
            self.transcript_path = os.path.join(OUTPUT_DIR, f"transcript_{timestamp}.txt")

    def stop_recording(self) -> str:
        """Stop recording and close WAV file. Returns WAV path for transcription."""
        with self._lock:
            self.running = False
            self.end_time = datetime.now()

            # Close WAV file
            wav_path = self.wav_path
            if self.wav_file:
                self.wav_file.close()
                self.wav_file = None

            return wav_path

    def set_transcribing(self, value: bool) -> None:
        with self._lock:
            self.transcribing = value

    def write_audio_frame(self, data: bytes) -> None:
        """Write audio data to WAV file."""
        with self._lock:
            if self.wav_file:
                self.wav_file.writeframes(data)
                self.total_frames += len(data) // 2  # 16-bit = 2 bytes per sample

    def is_running(self) -> bool:
        with self._lock:
            return self.running

    def add_transcript(self, timestamp: str, text: str) -> None:
        """Add a transcript segment (used after transcription completes)."""
        with self._lock:
            self.transcript_segments.append({"timestamp": timestamp, "text": text})

    def get_transcript_text(self) -> str:
        with self._lock:
            return "\n".join(
                f"{seg['timestamp']} {seg['text']}" for seg in self.transcript_segments
            )

    def load_transcript_file(self, filepath: str) -> bool:
        """Load a transcript from a file, including any embedded summary."""
        if not os.path.exists(filepath):
            return False

        with self._lock:
            self.transcript_segments = []
            self.chat_history = []
            self.loaded_file = filepath
            self.summary_text = None
            self.summary_status = "idle"
            self.summary_error = None

            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            # Split on summary header if present
            summary_marker = "## Meeting Summary"
            if summary_marker in content:
                transcript_part, summary_part = content.split(summary_marker, 1)
                self.summary_text = summary_part.strip()
                self.summary_status = "complete"
                # Seed chat history with summary for follow-up questions
                self.chat_history = [
                    {"role": "user", "content": "Summarize this meeting"},
                    {"role": "assistant", "content": self.summary_text},
                ]
            else:
                transcript_part = content

            # Parse transcript lines (lines starting with timestamps like [00:01:30])
            for line in transcript_part.split("\n"):
                line = line.strip()
                if line.startswith("[") and "]" in line:
                    bracket_end = line.index("]")
                    timestamp = line[: bracket_end + 1]
                    text = line[bracket_end + 1 :].strip()
                    if text:
                        self.transcript_segments.append({"timestamp": timestamp, "text": text})

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

    def set_summary_generating(self) -> None:
        """Set summary status to generating and clear error."""
        with self._lock:
            self.summary_status = "generating"
            self.summary_error = None

    def set_summary_complete(self, summary_text: str) -> None:
        """Set summary to complete with the given text and seed chat history."""
        with self._lock:
            self.summary_text = summary_text
            self.summary_status = "complete"
            # Seed chat history (prepend to preserve any existing messages)
            seed = [
                {"role": "user", "content": "Summarize this meeting"},
                {"role": "assistant", "content": summary_text},
            ]
            self.chat_history = seed + self.chat_history

    def set_summary_error(self, error: str) -> None:
        """Set summary status to error with the given message."""
        with self._lock:
            self.summary_status = "error"
            self.summary_error = error

    def is_summary_cancelled(self) -> bool:
        """Check if summary was cancelled (status reset to idle by start())."""
        with self._lock:
            return self.summary_status == "idle"

    def get_summary_state(self) -> dict[str, Any]:
        """Get current summary state."""
        with self._lock:
            return {
                "summary": self.summary_text,
                "status": self.summary_status,
                "error": self.summary_error,
            }

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            elapsed = 0
            if self.start_time:
                if self.running:
                    elapsed = int((datetime.now() - self.start_time).total_seconds())
                elif self.end_time:
                    elapsed = int((self.end_time - self.start_time).total_seconds())
            loaded_file = getattr(self, "loaded_file", "")
            return {
                "running": self.running,
                "transcribing": self.transcribing,
                "device": self.device_name,
                "elapsed_seconds": elapsed,
                "has_transcript": len(self.transcript_segments) > 0,
                "loaded_file": os.path.basename(loaded_file) if loaded_file else None,
                "wav_path": os.path.basename(self.wav_path) if self.wav_path else None,
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


_INACTIVE_BOT_STATES = {BotState.IDLE, BotState.MEETING_ENDED, BotState.ERROR, BotState.CLOSING}


class PlaywrightBotManager:
    """Manages the Playwright-based Zoom bot lifecycle."""

    def __init__(self) -> None:
        self._bot: ZoomWebBot | None = None
        self._lock = asyncio.Lock()

    def is_active(self) -> bool:
        """True when bot exists and state is not terminal."""
        return self._bot is not None and self._bot.state not in _INACTIVE_BOT_STATES

    def get_status(self) -> dict[str, Any]:
        """Return current bot status dict."""
        if self._bot is None:
            return {
                "bot_state": BotState.IDLE.value,
                "is_recording": False,
                "recording_duration": 0.0,
                "error_message": None,
            }
        return {
            "bot_state": self._bot.state.value,
            "is_recording": self._bot.is_recording(),
            "recording_duration": self._bot.get_recording_duration(),
            "error_message": self._bot.error_message,
        }

    async def start_bot(self, config: BotConfig) -> bool:
        """Start the bot in a thread executor. Returns True if join succeeded."""
        async with self._lock:
            if self._bot is not None and self._bot.state not in _INACTIVE_BOT_STATES:
                return False
            self._bot = ZoomWebBot(config)
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._bot.start)

    async def stop_bot(self) -> tuple[str, float] | None:
        """Stop audio capture, stop bot, return (wav_path, duration) or None."""
        async with self._lock:
            if self._bot is None:
                return None
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._bot.stop_audio_capture)
            await loop.run_in_executor(None, self._bot.stop)
            self._bot = None
            return result

    async def get_breakout_rooms(self) -> list[str]:
        """List available breakout rooms."""
        async with self._lock:
            if self._bot is None:
                return []
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._bot.get_available_breakout_rooms)

    async def join_breakout_room(self, room_name: str) -> bool:
        """Join a breakout room by name."""
        async with self._lock:
            if self._bot is None:
                return False
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._bot.join_breakout_room, room_name)


# Global state
state = TranscriptionState()
manager = ConnectionManager()
bot_manager = PlaywrightBotManager()
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


async def _generate_summary(transcript_text: str, transcript_path: str) -> None:
    """Generate a summary for the transcript and broadcast results.

    Args:
        transcript_text: Full transcript text with timestamps
        transcript_path: Path to transcript file (may be empty for Zoom bot path)
    """
    try:
        # Set status to generating
        state.set_summary_generating()
        await manager.broadcast({"type": "summary_started"})

        # Strip timestamps from transcript text
        lines = transcript_text.split("\n")
        plain_text_lines = []
        for line in lines:
            if "]" in line:
                plain_text = line.split("]", 1)[1].strip()
                if plain_text:
                    plain_text_lines.append(plain_text)
            elif line.strip():
                plain_text_lines.append(line.strip())

        plain_transcript = " ".join(plain_text_lines)

        # Call summarize_transcript via executor (blocking call)
        loop = asyncio.get_event_loop()
        summary_text = await loop.run_in_executor(None, summarize_transcript, plain_transcript)

        # Check if task was cancelled (new recording started)
        if state.is_summary_cancelled():
            return

        if summary_text is None:
            error_msg = "Summarization failed. Check AWS credentials and Bedrock access."
            state.set_summary_error(error_msg)
            await manager.broadcast({"type": "summary_error", "error": error_msg})
            return

        # Success - store results and seed chat
        state.set_summary_complete(summary_text)

        # Append summary to transcript file if path exists
        if transcript_path and os.path.exists(transcript_path):
            with open(transcript_path, "a", encoding="utf-8") as f:
                f.write("\n\n## Meeting Summary\n\n")
                f.write(summary_text)

        # Broadcast success
        await manager.broadcast({"type": "summary_complete", "summary": summary_text})

    except Exception as e:
        # Check if task was cancelled
        if state.is_summary_cancelled():
            return

        state.set_summary_error(str(e))
        await manager.broadcast({"type": "summary_error", "error": str(e)})


def transcribe_wav_file_streaming(
    model: WhisperModel, wav_path: str, audio_duration: float, progress_queue: Queue[dict[str, Any]]
) -> list[dict[str, str]]:
    """Transcribe a WAV file and send progress updates via queue.

    Returns list of {"timestamp": "[MM:SS]", "text": "..."} dicts.
    """
    segments_list: list[dict[str, str]] = []

    try:
        # faster-whisper can transcribe directly from file path
        segments, info = model.transcribe(
            wav_path,
            language=None,
            vad_filter=True,
            beam_size=5,
        )

        # Iterate through the generator - this yields segments as they're processed
        for segment in segments:
            text = segment.text.strip()
            if text:
                # Format timestamp as [MM:SS] or [HH:MM:SS]
                start_time = int(segment.start)
                hours, remainder = divmod(start_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    timestamp = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
                else:
                    timestamp = f"[{minutes:02d}:{seconds:02d}]"

                seg_data = {"timestamp": timestamp, "text": text}
                segments_list.append(seg_data)

                # Calculate progress based on segment end time vs total duration
                progress = min(segment.end / audio_duration, 1.0) if audio_duration > 0 else 0
                progress_queue.put(
                    {
                        "type": "progress",
                        "segment": seg_data,
                        "progress": progress,
                        "processed_seconds": segment.end,
                        "total_seconds": audio_duration,
                    }
                )

    except Exception as e:
        print(f"Transcription error: {e}")
        progress_queue.put({"type": "error", "error": str(e)})

    progress_queue.put({"type": "done", "segments": len(segments_list)})
    return segments_list


def audio_worker(device_idx: int) -> None:
    """Background worker for audio capture (recording only, no transcription)."""
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

        last_level_time = 0.0

        while state.is_running():
            try:
                # Read audio chunk
                data = stream.read(CHUNK, exception_on_overflow=False)

                # Write to WAV file (crash-safe incremental writes)
                state.write_audio_frame(data)

                # Send level updates (throttled)
                current_time = time.time()
                if current_time - last_level_time >= LEVEL_UPDATE_INTERVAL:
                    audio_chunk = np.frombuffer(data, dtype=np.int16)
                    level = float(np.abs(audio_chunk).mean())
                    level_queue.put(level)
                    last_level_time = current_time

            except Exception:
                continue

        stream.stop_stream()
        stream.close()

    finally:
        p.terminate()


async def broadcast_worker() -> None:
    """Async worker to broadcast queue contents to WebSocket clients."""
    loop = asyncio.get_event_loop()
    bot_status_interval = 0.5  # 500ms
    last_bot_status_time = 0.0
    bot_was_active = False

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

        # Broadcast bot status periodically
        now = time.time()
        bot_active = bot_manager.is_active()
        if now - last_bot_status_time >= bot_status_interval:
            if bot_active:
                await manager.broadcast({"type": "zoom_bot_status", **bot_manager.get_status()})
                last_bot_status_time = now
                bot_was_active = True
            elif bot_was_active:
                # Send one final status update so frontend knows the bot stopped
                await manager.broadcast({"type": "zoom_bot_status", **bot_manager.get_status()})
                last_bot_status_time = now
                bot_was_active = False

        await asyncio.sleep(0.05)  # 50ms polling interval


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown events."""
    # Start broadcast worker
    task = asyncio.create_task(broadcast_worker())
    yield
    # Cleanup
    task.cancel()
    if state.is_running():
        state.stop_recording()
    if bot_manager.is_active():
        await bot_manager.stop_bot()


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


@app.post("/api/reset")
async def reset_state() -> JSONResponse:
    """Reset stuck state (use if UI gets stuck)."""
    state.running = False
    state.transcribing = False
    await manager.broadcast({"type": "status", **state.get_status()})
    return JSONResponse(content={"status": "reset"})


@app.post("/api/start")
async def start_transcription(body: dict[str, Any]) -> JSONResponse:
    """Start transcription with specified device."""
    if state.is_running():
        return JSONResponse(status_code=400, content={"error": "Transcription already running"})

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
    """Stop recording and transcribe the audio."""
    if not state.is_running():
        return JSONResponse(status_code=400, content={"error": "Recording not running"})

    # Stop recording and get WAV path
    wav_path = state.stop_recording()

    # Wait for worker thread to finish
    if state.worker_thread:
        state.worker_thread.join(timeout=5.0)

    # Broadcast "stopped recording, transcribing" status
    state.set_transcribing(True)
    await manager.broadcast({"type": "status", **state.get_status()})

    # Check recording duration
    recording_duration = state.total_frames / RATE
    if recording_duration < 1.0:
        state.set_transcribing(False)
        await manager.broadcast({"type": "status", **state.get_status()})
        return JSONResponse(content={"status": "stopped", "message": "Recording too short"})

    try:
        # Transcribe the WAV file with streaming progress
        print(f"Loading model: {WHISPER_MODEL}...")
        model = load_model()
        print(f"Transcribing {wav_path} ({recording_duration:.1f}s of audio)...")

        # Create a queue for progress updates
        progress_queue: Queue[dict[str, Any]] = Queue()

        # Start transcription in background thread
        loop = asyncio.get_event_loop()
        transcription_task = loop.run_in_executor(
            None,
            lambda: transcribe_wav_file_streaming(
                model, wav_path, recording_duration, progress_queue
            ),
        )

        # Poll for progress updates while transcription runs
        segments: list[dict[str, str]] = []
        while True:
            try:
                # Check for progress updates (non-blocking)
                update = await loop.run_in_executor(None, lambda: progress_queue.get(timeout=0.1))

                if update["type"] == "progress":
                    # Broadcast progress and segment to clients
                    await manager.broadcast(
                        {
                            "type": "transcription_progress",
                            "progress": update["progress"],
                            "processed_seconds": update["processed_seconds"],
                            "total_seconds": update["total_seconds"],
                        }
                    )
                    # Also send the segment
                    seg = update["segment"]
                    state.add_transcript(seg["timestamp"], seg["text"])
                    await manager.broadcast(
                        {
                            "type": "transcript",
                            "timestamp": seg["timestamp"],
                            "text": seg["text"],
                        }
                    )
                    segments.append(seg)

                elif update["type"] == "error":
                    raise Exception(update["error"])

                elif update["type"] == "done":
                    print(f"Transcription complete: {update['segments']} segments")
                    break

            except Empty:
                # No update yet, check if task is done
                if transcription_task.done():
                    break
                continue

        # Wait for transcription to fully complete
        await transcription_task

        # Write transcript file
        if segments:
            with open(state.transcript_path, "w", encoding="utf-8") as f:
                f.write(
                    f"Transcript started: {state.start_time.strftime('%Y-%m-%d %H:%M:%S') if state.start_time else ''}\n"
                )
                f.write(f"Audio device: {state.device_name}\n")
                f.write(f"Audio file: {os.path.basename(wav_path)}\n")
                f.write(f"Model: {WHISPER_MODEL}\n")
                hours, remainder = divmod(int(recording_duration), 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = f"{minutes}:{seconds:02d}"
                f.write(f"Duration: {duration_str}\n")
                f.write("\n")
                for seg in segments:
                    f.write(f"{seg['timestamp']} {seg['text']}\n")

        # Trigger auto-summary if enabled and recording is long enough
        if AUTO_SUMMARIZE and recording_duration >= 30 and _has_aws_credentials():
            transcript_text = state.get_transcript_text()
            state._summary_task = asyncio.create_task(
                _generate_summary(transcript_text, state.transcript_path)
            )
        elif AUTO_SUMMARIZE and recording_duration >= 30:
            print("⚠️  Auto-summary skipped: AWS credentials not configured")

        # Done transcribing
        state.set_transcribing(False)
        await manager.broadcast({"type": "status", **state.get_status()})

        return JSONResponse(
            content={
                "status": "stopped",
                "segments": len(segments),
                "wav_path": os.path.basename(wav_path),
                "transcript_path": os.path.basename(state.transcript_path),
            }
        )

    except Exception as e:
        print(f"Transcription error: {e}")
        # Reset state on error
        state.set_transcribing(False)
        await manager.broadcast({"type": "status", **state.get_status()})
        return JSONResponse(status_code=500, content={"error": f"Transcription failed: {str(e)}"})


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
        # Broadcast summary state if summary was found in the file
        summary_state = state.get_summary_state()
        if summary_state["status"] == "complete":
            await manager.broadcast(
                {"type": "summary_complete", "summary": summary_state["summary"]}
            )
        return JSONResponse(
            content={
                "status": "loaded",
                "filename": filename,
                "segments": len(state.transcript_segments),
                **summary_state,
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

    # Send current summary state on connect
    await websocket.send_json({"type": "summary_state", **state.get_summary_state()})

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


@app.get("/api/summary")
async def get_summary() -> JSONResponse:
    """Get current summary state."""
    return JSONResponse(content=state.get_summary_state())


@app.post("/api/summary/generate")
async def generate_summary() -> JSONResponse:
    """Manually trigger summary generation."""
    summary_state = state.get_summary_state()
    if summary_state["status"] == "generating":
        return JSONResponse(
            status_code=409, content={"error": "Summary is already being generated"}
        )

    # Check for transcript text (local path or Zoom bot path)
    transcript_text = state.get_transcript_text()
    if not transcript_text and state.summary_transcript_text:
        transcript_text = state.summary_transcript_text
    if not transcript_text:
        return JSONResponse(status_code=400, content={"error": "No transcript available"})

    # Use transcript_path if available, empty string otherwise
    transcript_path = state.transcript_path or ""

    state._summary_task = asyncio.create_task(_generate_summary(transcript_text, transcript_path))
    return JSONResponse(content={"status": "generating"})


# =============================================================================
# Zoom Bot Integration (Playwright-based)
# =============================================================================


async def _run_zoom_bot(config: BotConfig) -> None:
    """Background task: start bot, join meeting, begin audio capture."""
    try:
        joined = await bot_manager.start_bot(config)
        if not joined:
            status = bot_manager.get_status()
            await manager.broadcast(
                {
                    "type": "zoom_bot_status",
                    **status,
                }
            )
            return

        # Start audio capture in executor (sync call)
        loop = asyncio.get_event_loop()
        async with bot_manager._lock:
            if bot_manager._bot is not None:
                await loop.run_in_executor(None, bot_manager._bot.start_audio_capture)

        await manager.broadcast({"type": "zoom_bot_status", **bot_manager.get_status()})
    except Exception as e:
        print(f"Zoom bot error: {e}")
        await manager.broadcast(
            {
                "type": "zoom_bot_status",
                "bot_state": BotState.ERROR.value,
                "is_recording": False,
                "recording_duration": 0.0,
                "error_message": str(e),
            }
        )


async def _transcribe_zoom_audio(wav_path: str, duration: float) -> None:
    """Background task: transcribe zoom audio and broadcast results."""
    try:
        print(f"Loading model for Zoom transcription: {WHISPER_MODEL}...")
        model = load_model()
        print(f"Transcribing Zoom audio {wav_path} ({duration:.1f}s)...")

        progress_queue: Queue[dict[str, Any]] = Queue()
        loop = asyncio.get_event_loop()

        transcription_future = loop.run_in_executor(
            None,
            lambda: transcribe_wav_file_streaming(model, wav_path, duration, progress_queue),
        )

        segments: list[dict[str, str]] = []
        while True:
            try:
                update = await loop.run_in_executor(None, lambda: progress_queue.get(timeout=0.1))
                if update["type"] == "progress":
                    seg = update["segment"]
                    segments.append(seg)
                    await manager.broadcast(
                        {
                            "type": "zoom_bot_transcript",
                            "timestamp": seg["timestamp"],
                            "text": seg["text"],
                        }
                    )
                elif update["type"] == "error":
                    print(f"Zoom transcription error: {update['error']}")
                    break
                elif update["type"] == "done":
                    print(f"Zoom transcription complete: {update['segments']} segments")
                    break
            except Empty:
                if transcription_future.done():
                    break
                continue

        await transcription_future

        # Save transcript file
        if segments:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            transcript_path = os.path.join(OUTPUT_DIR, f"transcript_zoom_{timestamp}.txt")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write("Zoom Meeting Transcript\n")
                f.write(f"Audio file: {os.path.basename(wav_path)}\n")
                f.write(f"Model: {WHISPER_MODEL}\n")
                hours, remainder = divmod(int(duration), 3600)
                minutes, seconds = divmod(remainder, 60)
                dur_str = (
                    f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
                )
                f.write(f"Duration: {dur_str}\n\n")
                for seg in segments:
                    f.write(f"{seg['timestamp']} {seg['text']}\n")
            print(f"Zoom transcript saved: {transcript_path}")

            await manager.broadcast(
                {
                    "type": "zoom_bot_event",
                    "event": "transcription_complete",
                    "segments": len(segments),
                    "transcript_path": os.path.basename(transcript_path),
                }
            )

            # Build transcript text from segments and trigger auto-summary
            transcript_text = "\n".join(f"{seg['timestamp']} {seg['text']}" for seg in segments)
            # Store for manual re-generation
            state.summary_transcript_text = transcript_text
            if AUTO_SUMMARIZE and duration >= 30 and _has_aws_credentials():
                state._summary_task = asyncio.create_task(
                    _generate_summary(transcript_text, transcript_path)
                )
            elif AUTO_SUMMARIZE and duration >= 30:
                print("⚠️  Auto-summary skipped: AWS credentials not configured")

    except Exception as e:
        print(f"Zoom transcription failed: {e}")


@app.post("/api/zoom-bot/start")
async def zoom_bot_start(body: dict[str, Any]) -> JSONResponse:
    """Start the Playwright Zoom bot."""
    meeting_url = body.get("meeting_url", "")
    if not meeting_url:
        return JSONResponse(status_code=400, content={"error": "meeting_url required"})

    if bot_manager.is_active():
        return JSONResponse(status_code=409, content={"error": "Bot is already active"})

    config = BotConfig(
        meeting_url=meeting_url,
        bot_name=body.get("bot_name", "Transcription Bot"),
        meeting_password=body.get("meeting_password", ""),
    )
    asyncio.create_task(_run_zoom_bot(config))
    return JSONResponse(content={"status": "starting"})


@app.post("/api/zoom-bot/stop")
async def zoom_bot_stop() -> JSONResponse:
    """Stop the Playwright Zoom bot and transcribe captured audio."""
    if not bot_manager.is_active():
        # Idempotent: if bot is already stopped, broadcast idle state and return success
        await manager.broadcast({"type": "zoom_bot_status", **bot_manager.get_status()})
        return JSONResponse(content={"status": "stopped", "wav_path": None, "duration": 0})

    result = await bot_manager.stop_bot()
    if result:
        wav_path, duration = result
        asyncio.create_task(_transcribe_zoom_audio(wav_path, duration))
        return JSONResponse(
            content={
                "status": "stopped",
                "wav_path": os.path.basename(wav_path),
                "duration": duration,
            }
        )
    return JSONResponse(content={"status": "stopped", "wav_path": None, "duration": 0})


@app.get("/api/zoom-bot/status")
async def zoom_bot_status() -> dict[str, Any]:
    """Get Zoom bot status."""
    return bot_manager.get_status()


@app.get("/api/zoom-bot/breakout-rooms")
async def zoom_bot_breakout_rooms() -> JSONResponse:
    """List available breakout rooms."""
    if not bot_manager.is_active():
        return JSONResponse(status_code=400, content={"error": "Bot is not active"})
    try:
        rooms = await bot_manager.get_breakout_rooms()
        return JSONResponse(content={"rooms": rooms})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/zoom-bot/join-breakout")
async def zoom_bot_join_breakout(body: dict[str, Any]) -> JSONResponse:
    """Join a breakout room."""
    room_name = body.get("room_name", "")
    if not room_name:
        return JSONResponse(status_code=400, content={"error": "room_name required"})
    if not bot_manager.is_active():
        return JSONResponse(status_code=400, content={"error": "Bot is not active"})
    try:
        success = await bot_manager.join_breakout_room(room_name)
        return JSONResponse(content={"success": success})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    print(f"Starting server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
