#!/usr/bin/env python3
"""
Live audio transcription using faster-whisper and BlackHole for macOS.

This script captures audio from a BlackHole device and transcribes it in real-time
using the faster-whisper library. Press Ctrl+C to stop.
"""

import os
import signal
import sys
from datetime import datetime

import numpy as np
import pyaudio
from dotenv import load_dotenv
from faster_whisper import WhisperModel

# Load environment variables
load_dotenv()

# Configuration
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
DEVICE = os.getenv("DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
CHUNK_DURATION = int(os.getenv("CHUNK_DURATION", "30"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "transcripts")

# Audio settings
RATE = 16000  # Sample rate in Hz (Whisper uses 16kHz)
CHANNELS = 1  # Mono audio
CHUNK = 1024  # Buffer size
FORMAT = pyaudio.paInt16  # 16-bit audio

# Global flag for graceful shutdown
running = True


def signal_handler(sig, frame):
    """Handle Ctrl+C for graceful shutdown."""
    global running
    print("\n\n🛑 Stopping transcription...")
    running = False


def create_transcript_file():
    """Create a new transcript file with timestamp in filename."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"transcript_{timestamp}.txt"
    return os.path.join(OUTPUT_DIR, filename)


def format_elapsed_time(start_time):
    """Format elapsed time as [HH:MM:SS]."""
    elapsed = datetime.now() - start_time
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"


def format_duration(start_time, end_time):
    """Format duration as H:MM:SS."""
    elapsed = end_time - start_time
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def list_audio_devices():
    """List all available audio devices and return device info."""
    p = pyaudio.PyAudio()
    devices = []

    print("\n🎤 Available Audio Devices:")
    print("-" * 60)

    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        devices.append(info)

        # Highlight BlackHole devices
        is_blackhole = "BlackHole" in info["name"]
        prefix = "➜ " if is_blackhole else "  "

        print(f"{prefix}[{i}] {info['name']}")
        print(f"    Input channels: {info['maxInputChannels']}")
        print(f"    Output channels: {info['maxOutputChannels']}")
        if is_blackhole:
            print("    ⭐ BlackHole device detected!")
        print()

    p.terminate()
    return devices


def select_input_device(devices):
    """Prompt user to select an input device."""
    # Try to auto-select BlackHole device
    blackhole_devices = [
        i for i, d in enumerate(devices) if "BlackHole" in d["name"] and d["maxInputChannels"] > 0
    ]

    if blackhole_devices:
        default_device = blackhole_devices[0]
        print(
            f"✅ Auto-selected BlackHole device: [{default_device}] {devices[default_device]['name']}"
        )

        # Ask if user wants to use this device
        choice = input("\nUse this device? (Y/n): ").strip().lower()
        if choice in ["", "y", "yes"]:
            return default_device

    # Manual selection
    while True:
        try:
            device_idx = input("\n🔢 Enter device number: ").strip()
            device_idx = int(device_idx)

            if 0 <= device_idx < len(devices):
                if devices[device_idx]["maxInputChannels"] > 0:
                    return device_idx
                else:
                    print("❌ This device has no input channels. Please select another.")
            else:
                print(f"❌ Invalid device number. Please enter 0-{len(devices) - 1}")
        except ValueError:
            print("❌ Please enter a valid number.")
        except KeyboardInterrupt:
            print("\n\n👋 Exiting...")
            sys.exit(0)


def load_whisper_model():
    """Load the Whisper model."""
    print(f"\n📥 Loading Whisper model: {WHISPER_MODEL}")
    print(f"   Device: {DEVICE}")
    print(f"   Compute type: {COMPUTE_TYPE}")
    print("   (First run will download the model, this may take a few minutes...)")

    try:
        model = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type=COMPUTE_TYPE)
        print("✅ Model loaded successfully!\n")
        return model
    except Exception as e:
        print(f"\n❌ Error loading model: {e}")
        print("\nTroubleshooting tips:")
        print("  1. Check your internet connection (model needs to download)")
        print("  2. Try a smaller model (tiny, base)")
        print("  3. Verify DEVICE and COMPUTE_TYPE settings in .env")
        sys.exit(1)


def transcribe_audio_buffer(model, audio_data, sample_rate):
    """Transcribe an audio buffer using Whisper."""
    try:
        # Whisper expects audio as float32 normalized to [-1, 1]
        audio_float = audio_data.astype(np.float32) / 32768.0

        # Transcribe
        segments, info = model.transcribe(
            audio_float,
            language=None,  # Auto-detect language
            vad_filter=True,  # Use Voice Activity Detection
            beam_size=5,
        )

        # Collect all segments
        text = " ".join([segment.text.strip() for segment in segments])
        return text

    except Exception as e:
        print(f"\n⚠️  Transcription error: {e}")
        return None


def main():
    """Main function to run live transcription."""
    global running

    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    print("=" * 60)
    print("🎙️  Live Audio Transcription with faster-whisper")
    print("=" * 60)

    # List and select audio device
    devices = list_audio_devices()
    device_idx = select_input_device(devices)

    # Load Whisper model
    model = load_whisper_model()

    # Initialize PyAudio
    p = pyaudio.PyAudio()

    # Create transcript file
    transcript_path = create_transcript_file()
    device_name = devices[device_idx]["name"]
    start_time = datetime.now()

    try:
        # Open audio stream
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=device_idx,
            frames_per_buffer=CHUNK,
        )

        # Open transcript file and write header
        transcript_file = open(transcript_path, "w", encoding="utf-8")
        transcript_file.write(f"Transcript started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        transcript_file.write(f"Audio device: {device_name}\n")
        transcript_file.write(f"Model: {WHISPER_MODEL}\n")
        transcript_file.write("\n")
        transcript_file.flush()

        print("=" * 60)
        print("🎤 Recording started! Speak or play audio...")
        print(f"⏱️  Buffer duration: {CHUNK_DURATION} seconds")
        print(f"📝 Saving to: {transcript_path}")
        print("🛑 Press Ctrl+C to stop")
        print("=" * 60)
        print()

        # Calculate number of chunks for buffer duration
        chunks_per_buffer = int(RATE / CHUNK * CHUNK_DURATION)
        audio_buffer = []
        chunk_count = 0
        level_display_interval = int(RATE / CHUNK * 0.5)  # Update level every 0.5 seconds
        level_counter = 0

        while running:
            try:
                # Read audio chunk
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_chunk = np.frombuffer(data, dtype=np.int16)
                audio_buffer.append(audio_chunk)
                chunk_count += 1
                level_counter += 1

                # Show audio level periodically so user knows it's working
                if level_counter >= level_display_interval:
                    level = np.abs(audio_chunk).mean()
                    # Create a simple level meter (0-50 scale)
                    bar_length = min(int(level / 500), 30)
                    bar = "█" * bar_length + "░" * (30 - bar_length)
                    elapsed = chunk_count * CHUNK / RATE
                    remaining = CHUNK_DURATION - elapsed
                    print(
                        f"\r🎚️  [{bar}] {level:5.0f}  ⏱️ {remaining:.0f}s until transcribe",
                        end="",
                        flush=True,
                    )
                    level_counter = 0

                # Process buffer when full
                if chunk_count >= chunks_per_buffer:
                    print()  # New line after the level meter
                    # Concatenate all chunks
                    audio_data = np.concatenate(audio_buffer)

                    # Check if there's actual audio (not silence)
                    avg_level = np.abs(audio_data).mean()
                    if avg_level > 10:  # Simple silence detection
                        print(f"🔄 Transcribing... (avg level: {avg_level:.0f})")
                        text = transcribe_audio_buffer(model, audio_data, RATE)

                        if text and text.strip():
                            timestamp = format_elapsed_time(start_time)
                            print(f"💬 {text}")
                            print()
                            # Write to transcript file
                            transcript_file.write(f"{timestamp} {text}\n")
                            transcript_file.flush()
                        else:
                            print("   (no speech detected)")
                            print()
                    else:
                        print(f"   (silence - avg level: {avg_level:.0f})")
                        print()

                    # Reset buffer
                    audio_buffer = []
                    chunk_count = 0

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\n⚠️  Error reading audio: {e}")
                continue

        # Clean up
        stream.stop_stream()
        stream.close()
        p.terminate()

        # Write transcript footer and close
        end_time = datetime.now()
        transcript_file.write("\n---\n")
        transcript_file.write(f"Transcript ended: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        transcript_file.write(f"Duration: {format_duration(start_time, end_time)}\n")
        transcript_file.close()

        print("\n" + "=" * 60)
        print("✅ Transcription stopped. Goodbye!")
        print(f"📝 Transcript saved to: {transcript_path}")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        p.terminate()
        sys.exit(1)


if __name__ == "__main__":
    main()
