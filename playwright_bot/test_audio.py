#!/usr/bin/env python3
"""Test script for audio capture in Zoom meetings.

This script tests the audio capture functionality by joining a Zoom meeting,
capturing audio until stopped, and optionally transcribing it.

Usage:
    # Basic test (indefinite, until Ctrl+C)
    python playwright_bot/test_audio.py "https://zoom.us/j/123456789"

    # Headed mode with specific duration
    python playwright_bot/test_audio.py "https://zoom.us/j/123456789" --headed --duration 60

    # Test with breakout room
    python playwright_bot/test_audio.py "https://zoom.us/j/123456789" --room "Room 1"

    # Test and transcribe the recording
    python playwright_bot/test_audio.py "https://zoom.us/j/123456789" --headed --transcribe
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from playwright_bot.zoom_web_bot import BotConfig, ZoomWebBot

# Load environment variables
load_dotenv()

# Global flag for graceful shutdown
running = True


def signal_handler(sig: int, frame: object) -> None:
    """Handle Ctrl+C for graceful shutdown."""
    global running
    print("\n\n   Stopping audio capture...")
    running = False


def format_duration(seconds: float) -> str:
    """Format duration as MM:SS or HH:MM:SS."""
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def transcribe_wav_file(wav_path: str) -> str | None:
    """Transcribe a WAV file using faster-whisper.

    Args:
        wav_path: Path to WAV file

    Returns:
        Timestamped transcript text or None if transcription failed
    """
    try:
        from faster_whisper import WhisperModel

        model_name = os.getenv("WHISPER_MODEL", "large-v3-turbo")
        device = os.getenv("DEVICE", "cpu")
        compute_type = os.getenv("COMPUTE_TYPE", "int8")

        print(f"\n   Loading Whisper model: {model_name}")
        print(f"   Device: {device}, Compute type: {compute_type}")

        model = WhisperModel(model_name, device=device, compute_type=compute_type)

        print(f"   Transcribing: {wav_path}")

        segments, info = model.transcribe(
            wav_path,
            language=None,
            vad_filter=True,
            beam_size=5,
        )

        print(
            f"   Detected language: {info.language} (probability: {info.language_probability:.2f})"
        )

        # Collect segments with timestamps
        transcript_lines = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                start_time = int(segment.start)
                hours, remainder = divmod(start_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    timestamp = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
                else:
                    timestamp = f"[{minutes:02d}:{seconds:02d}]"
                transcript_lines.append(f"{timestamp} {text}")

        if transcript_lines:
            return "\n".join(transcript_lines)
        return None

    except ImportError:
        print("\n   faster-whisper not installed. Install with: pip install faster-whisper")
        return None
    except Exception as e:
        print(f"\n   Transcription error: {e}")
        return None


def main() -> None:
    """Main function to test audio capture."""
    global running

    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Test audio capture in Zoom meetings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("meeting_url", help="Zoom meeting URL")
    parser.add_argument("--name", default="Audio Test Bot", help="Bot display name")
    parser.add_argument("--password", default="", help="Meeting password")
    parser.add_argument("--headed", action="store_true", help="Run in headed mode")
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Recording duration in seconds (default: indefinite, until Ctrl+C)",
    )
    parser.add_argument("--room", default="", help="Breakout room to join")
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Transcribe the recording after capture",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("OUTPUT_DIR", "transcripts"),
        help="Output directory for recordings",
    )

    args = parser.parse_args()

    # Display banner
    print("=" * 60)
    print("   Zoom Audio Capture Test")
    print("=" * 60)
    print(f"\n   Meeting URL: {args.meeting_url}")
    print(f"   Bot Name: {args.name}")
    print(f"   Headless: {not args.headed}")
    if args.duration:
        print(f"   Duration: {args.duration}s")
    else:
        print("   Duration: Indefinite (Ctrl+C to stop)")
    print(f"   Output Dir: {args.output_dir}")
    if args.room:
        print(f"   Target Room: {args.room}")
    if args.transcribe:
        print("   Transcription: Enabled")
    print()

    # Create bot config
    config = BotConfig(
        meeting_url=args.meeting_url,
        bot_name=args.name,
        meeting_password=args.password,
        headless=not args.headed,
        breakout_room=args.room,
        enable_audio_capture=True,
        audio_output_dir=args.output_dir,
    )

    bot = ZoomWebBot(config)
    wav_path = None

    try:
        # Join meeting
        print("   Joining meeting...")
        if not bot.start():
            print(f"\n   Failed to join meeting: {bot.error_message}")
            return

        print("\n   Successfully joined meeting!")
        print(f"   State: {bot.get_state().value}")

        # Handle breakout room if specified
        if args.room:
            print("\n   Waiting for breakout rooms...")
            if bot.wait_for_breakout_rooms(timeout_ms=60000):
                print("   Breakout rooms available!")
                rooms = bot.get_available_breakout_rooms()
                print(f"   Available rooms: {', '.join(rooms)}")

                print(f"   Joining room: {args.room}")
                if bot.join_breakout_room(args.room):
                    print("   Successfully joined breakout room!")
                else:
                    print("   Failed to join breakout room")
                    return
            else:
                print("   Breakout rooms not available (continuing in main meeting)")

        # Start audio capture
        print("\n   Starting audio capture...")
        if not bot.start_audio_capture():
            print("   Failed to start audio capture!")
            return

        wav_path = bot.get_recording_path()
        print(f"   Recording to: {wav_path}")
        if args.duration:
            print(f"   Duration: {args.duration}s")
            print("   Press Ctrl+C to stop early")
        else:
            print("   Duration: Indefinite")
            print("   Press Ctrl+C to stop")
        print()
        print("=" * 60)

        # Record until stopped or duration reached
        start_time = time.time()
        while running:
            elapsed = time.time() - start_time

            # Check duration limit if specified
            if args.duration and elapsed >= args.duration:
                break

            # Show progress
            duration = bot.get_recording_duration()

            if args.duration:
                remaining = args.duration - elapsed
                print(
                    f"\r   Recording: {format_duration(duration)} "
                    f"| Remaining: {format_duration(remaining)}   ",
                    end="",
                    flush=True,
                )
            else:
                print(
                    f"\r   Recording: {format_duration(duration)} "
                    f"| Elapsed: {format_duration(elapsed)}   ",
                    end="",
                    flush=True,
                )

            time.sleep(0.5)

        print("\n")
        print("=" * 60)

        # Stop audio capture
        print("   Stopping audio capture...")
        result = bot.stop_audio_capture()

        if result:
            wav_path, duration = result
            print("\n   Recording complete!")
            print(f"   Duration: {format_duration(duration)}")
            print(f"   File: {wav_path}")

            # Transcribe if requested
            if args.transcribe and duration >= 1.0:
                print("\n" + "=" * 60)
                print("   Transcribing recording...")
                print("=" * 60)

                transcript = transcribe_wav_file(wav_path)

                if transcript:
                    print("\n   Transcript:")
                    print("-" * 60)
                    print(transcript)
                    print("-" * 60)

                    # Save transcript
                    transcript_path = wav_path.replace(".wav", "_transcript.txt")
                    with open(transcript_path, "w", encoding="utf-8") as f:
                        f.write("Audio Capture Test Transcript\n")
                        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Audio File: {wav_path}\n")
                        f.write(f"Duration: {format_duration(duration)}\n")
                        f.write("\n")
                        f.write(transcript)
                        f.write("\n")

                    print(f"\n   Transcript saved to: {transcript_path}")
                else:
                    print("\n   No speech detected in recording")
            elif args.transcribe:
                print("\n   Recording too short for transcription")
        else:
            print("   No audio was recorded")

    except Exception as e:
        print(f"\n   Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print("\n   Cleaning up...")
        bot.stop()
        print("   Done!")


if __name__ == "__main__":
    main()
