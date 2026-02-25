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

# Load environment variables
load_dotenv()

# Configuration (reuse from transcribe_live.py settings)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
DEVICE = os.getenv("DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")

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
    if state.is_running():
        state.stop_recording()


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


# =============================================================================
# Zoom Bot Integration (Docker-based Meeting SDK)
# =============================================================================

# Zoom bot state
zoom_bot_state = {
    "connected": False,
    "meeting_number": None,
    "audio_buffer": b"",
    "total_audio_bytes": 0,
}


@app.websocket("/zoom-audio")
async def zoom_audio_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for receiving audio from Zoom bot.

    The Docker-based Zoom bot connects here to stream audio.
    Audio is accumulated and can be transcribed when the meeting ends.
    """
    await websocket.accept()
    print("Zoom bot connected")
    zoom_bot_state["connected"] = True

    # Create WAV file for this session
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    wav_path = os.path.join(OUTPUT_DIR, f"zoom_meeting_{timestamp}.wav")

    # Open WAV file for writing
    wav_file = wave.open(wav_path, "wb")
    wav_file.setnchannels(1)  # Mono
    wav_file.setsampwidth(2)  # 16-bit
    wav_file.setframerate(16000)  # 16kHz

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.receive":
                if "bytes" in message:
                    # Binary audio data
                    audio_data = message["bytes"]
                    wav_file.writeframes(audio_data)
                    zoom_bot_state["total_audio_bytes"] += len(audio_data)

                elif "text" in message:
                    # JSON control message
                    try:
                        data = json.loads(message["text"])
                        msg_type = data.get("type", "")

                        if msg_type == "bot_connected":
                            print(f"Zoom bot connected: {data.get('bot_name', 'unknown')}")
                            await manager.broadcast(
                                {
                                    "type": "zoom_bot_event",
                                    "event": "connected",
                                    "bot_name": data.get("bot_name", ""),
                                }
                            )

                        elif msg_type == "meeting_joined":
                            zoom_bot_state["meeting_number"] = data.get("meeting_number")
                            await manager.broadcast(
                                {
                                    "type": "zoom_bot_event",
                                    "event": "meeting_joined",
                                    "meeting_number": data.get("meeting_number"),
                                }
                            )

                        elif msg_type == "meeting_left":
                            zoom_bot_state["meeting_number"] = None
                            await manager.broadcast(
                                {
                                    "type": "zoom_bot_event",
                                    "event": "meeting_left",
                                }
                            )

                        elif msg_type == "keepalive":
                            pass  # Just keep connection alive

                    except json.JSONDecodeError:
                        pass

    except WebSocketDisconnect:
        print("Zoom bot disconnected")
    finally:
        wav_file.close()
        zoom_bot_state["connected"] = False

        # If we have audio, transcribe it
        if zoom_bot_state["total_audio_bytes"] > 32000:  # At least 1 second
            print(f"Transcribing Zoom audio: {wav_path}")

            # Transcribe the recorded audio
            model = load_model()
            audio_duration = zoom_bot_state["total_audio_bytes"] / (2 * 16000)
            progress_queue: Queue[dict[str, Any]] = Queue()
            segments = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: transcribe_wav_file_streaming(
                    model, wav_path, audio_duration, progress_queue
                ),
            )

            # Save transcript
            if segments:
                transcript_path = wav_path.replace(".wav", ".txt")
                with open(transcript_path, "w", encoding="utf-8") as f:
                    f.write("Zoom Meeting Transcript\n")
                    f.write(f"Recorded: {timestamp}\n\n")
                    for seg in segments:
                        f.write(f"{seg['timestamp']} {seg['text']}\n")

                print(f"Transcript saved: {transcript_path}")

                # Broadcast completion
                await manager.broadcast(
                    {
                        "type": "zoom_bot_event",
                        "event": "transcription_complete",
                        "segments": len(segments),
                        "transcript_path": os.path.basename(transcript_path),
                    }
                )

        zoom_bot_state["total_audio_bytes"] = 0


@app.get("/api/zoom/bot-status")
async def zoom_bot_status() -> dict[str, Any]:
    """Get Zoom bot connection status."""
    return {
        "connected": zoom_bot_state["connected"],
        "meeting_number": zoom_bot_state["meeting_number"],
        "audio_received_bytes": zoom_bot_state["total_audio_bytes"],
    }


@app.post("/api/zoom/join")
async def zoom_join_meeting(body: dict[str, Any]) -> JSONResponse:
    """Send join command to Zoom bot.

    Requires the bot to be running (docker-compose up).
    """
    import websockets as ws_client

    meeting_number = body.get("meeting_number", "")
    password = body.get("password", "")
    display_name = body.get("display_name", "Transcription Bot")

    if not meeting_number:
        return JSONResponse(status_code=400, content={"error": "meeting_number required"})

    try:
        # Connect to the bot's command server
        bot_url = os.getenv("ZOOM_BOT_URL", "ws://localhost:3001")
        async with ws_client.connect(bot_url) as websocket:
            # Send join command
            await websocket.send(
                json.dumps(
                    {
                        "type": "join",
                        "meeting_number": meeting_number,
                        "password": password,
                        "display_name": display_name,
                    }
                )
            )

            # Wait for response
            response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
            result = json.loads(response)

            if result.get("success"):
                return JSONResponse(
                    content={
                        "status": "joining",
                        "meeting_number": meeting_number,
                    }
                )
            else:
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": result.get("error", "Join failed"),
                    },
                )

    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"error": "Bot response timeout"})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to connect to bot: {e}. Is the bot running?",
            },
        )


@app.post("/api/zoom/leave")
async def zoom_leave_meeting() -> JSONResponse:
    """Send leave command to Zoom bot."""
    import websockets as ws_client

    try:
        bot_url = os.getenv("ZOOM_BOT_URL", "ws://localhost:3001")
        async with ws_client.connect(bot_url) as websocket:
            await websocket.send(json.dumps({"type": "leave"}))
            response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            result = json.loads(response)

            return JSONResponse(content={"status": "left" if result.get("success") else "failed"})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    print(f"Starting server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
