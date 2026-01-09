#!/usr/bin/env python3
"""
Live audio transcription using faster-whisper and BlackHole for macOS.

This script captures audio from a BlackHole device and transcribes it in real-time
using the faster-whisper library. Press Ctrl+C to stop.
"""

import argparse
import json
import os
import signal
import sys
import wave
from datetime import datetime

import boto3
import numpy as np
import pyaudio
from dotenv import load_dotenv
from faster_whisper import WhisperModel

# Load environment variables
load_dotenv()

# Configuration
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
DEVICE = os.getenv("DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "transcripts")

# AWS Bedrock Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")

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


def create_wav_file() -> tuple[str, wave.Wave_write]:
    """Create a new WAV file for recording with timestamp in filename.

    Returns:
        Tuple of (filepath, wave file handle)
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"recording_{timestamp}.wav"
    filepath = os.path.join(OUTPUT_DIR, filename)

    wf = wave.open(filepath, "wb")
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)  # 16-bit audio = 2 bytes
    wf.setframerate(RATE)

    return filepath, wf


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


def summarize_transcript(transcript_text: str) -> str | None:
    """Summarize transcript using AWS Bedrock."""
    if not transcript_text.strip():
        return None

    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        prompt = (
            """Please summarize this meeting transcript. Provide:

1. **Key Points** - Main topics and decisions discussed (bullet points)
2. **Action Items** - Any tasks, follow-ups, or commitments mentioned (bullet points with owner if mentioned)

Keep it concise and actionable.

Transcript:
"""
            + transcript_text
        )

        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ),
        )

        result = json.loads(response["body"].read())
        return result["content"][0]["text"]

    except Exception as e:
        print(f"\n⚠️  Summarization error: {e}")
        print("   Transcript saved but summary generation failed.")
        print("   Check AWS credentials and Bedrock access.")
        return None


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


def transcribe_wav_file(model: WhisperModel, wav_path: str) -> str | None:
    """Transcribe a complete WAV file using Whisper.

    faster-whisper handles long files efficiently with internal chunking.
    Returns timestamped transcript lines.

    Args:
        model: Loaded Whisper model
        wav_path: Path to WAV file

    Returns:
        Timestamped transcript text or None if transcription failed
    """
    try:
        print(f"   Loading audio file: {wav_path}")

        # faster-whisper can transcribe directly from file path
        segments, info = model.transcribe(
            wav_path,
            language=None,  # Auto-detect language
            vad_filter=True,  # Use Voice Activity Detection
            beam_size=5,
        )

        print(f"   Detected language: {info.language} (probability: {info.language_probability:.2f})")
        print("   Transcribing...")

        # Collect all segments with their timestamps
        transcribed_segments = []
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
                transcribed_segments.append(f"{timestamp} {text}")

        if transcribed_segments:
            return "\n".join(transcribed_segments)
        return None

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

    # Create transcript and WAV files
    transcript_path = create_transcript_file()
    wav_path, wav_file = create_wav_file()
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

        print("=" * 60)
        print("🎤 Recording started! Speak or play audio...")
        print(f"🎵 Saving audio to: {wav_path}")
        print(f"📝 Transcript will be saved to: {transcript_path}")
        print("🛑 Press Ctrl+C to stop recording and transcribe")
        print("=" * 60)
        print()

        # Recording loop variables
        level_display_interval = int(RATE / CHUNK * 0.5)  # Update level every 0.5 seconds
        level_counter = 0
        total_frames = 0

        while running:
            try:
                # Read audio chunk
                data = stream.read(CHUNK, exception_on_overflow=False)

                # Write to WAV file immediately (crash safety)
                wav_file.writeframes(data)

                # Update counters
                audio_chunk = np.frombuffer(data, dtype=np.int16)
                total_frames += len(audio_chunk)
                level_counter += 1

                # Show audio level meter periodically
                if level_counter >= level_display_interval:
                    level = np.abs(audio_chunk).mean()
                    bar_length = min(int(level / 500), 30)
                    bar = "█" * bar_length + "░" * (30 - bar_length)

                    # Calculate elapsed time
                    elapsed_seconds = total_frames / RATE
                    hours, remainder = divmod(int(elapsed_seconds), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    if hours > 0:
                        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    else:
                        time_str = f"{minutes:02d}:{seconds:02d}"

                    print(
                        f"\r🎚️  [{bar}] {level:5.0f}  ⏱️ Recording: {time_str}",
                        end="",
                        flush=True,
                    )
                    level_counter = 0

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\n⚠️  Error reading audio: {e}")
                continue

        # Clean up audio stream
        print("\n")
        stream.stop_stream()
        stream.close()
        p.terminate()

        # Close WAV file
        wav_file.close()

        # Calculate recording duration
        recording_duration = total_frames / RATE
        hours, remainder = divmod(int(recording_duration), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            duration_str = f"{minutes}:{seconds:02d}"

        print("=" * 60)
        print("🛑 Recording stopped!")
        print(f"   Duration: {duration_str}")
        print(f"   Audio saved to: {wav_path}")
        print("=" * 60)
        print()

        # Check if recording is too short
        if recording_duration < 1.0:
            print("⚠️  Recording too short - no transcription generated")
            return

        # Transcribe the full recording
        print("🔄 Transcribing audio...")
        print("   (This may take a while for long recordings)")
        print()

        transcript_text = transcribe_wav_file(model, wav_path)

        # Open transcript file and write content
        transcript_file = open(transcript_path, "w", encoding="utf-8")
        transcript_file.write(f"Transcript started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        transcript_file.write(f"Audio device: {device_name}\n")
        transcript_file.write(f"Audio file: {wav_path}\n")
        transcript_file.write(f"Model: {WHISPER_MODEL}\n")
        transcript_file.write(f"Duration: {duration_str}\n")
        transcript_file.write("\n")

        if transcript_text:
            # Write transcript
            transcript_file.write(transcript_text)
            transcript_file.write("\n")
            transcript_file.flush()

            # Display transcript
            print("=" * 60)
            print("📝 Transcript:")
            print("=" * 60)
            print(transcript_text)
            print()

            # Generate summary
            print("🤖 Generating meeting summary...")
            # Strip timestamps for summary input
            plain_text = " ".join(
                line.split("]", 1)[1].strip() if "]" in line else line
                for line in transcript_text.split("\n")
                if line.strip()
            )
            summary = summarize_transcript(plain_text)

            if summary:
                transcript_file.write("\n---\n")
                transcript_file.write("## Meeting Summary\n\n")
                transcript_file.write(summary)
                transcript_file.write("\n")

                print("\n" + "=" * 60)
                print("📋 Meeting Summary:")
                print("=" * 60)
                print(summary)
        else:
            print("   (No speech detected in recording)")
            transcript_file.write("(No speech detected)\n")

        transcript_file.close()

        print("\n" + "=" * 60)
        print("✅ Done!")
        print(f"🎵 Audio saved to: {wav_path}")
        print(f"📝 Transcript saved to: {transcript_path}")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        p.terminate()
        sys.exit(1)


def summarize_existing_file(filepath: str) -> None:
    """Summarize an existing transcript file."""
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        sys.exit(1)

    print(f"📄 Reading transcript: {filepath}")

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # Extract just the transcript lines (lines starting with timestamps like [00:01:30])
    lines = content.split("\n")
    transcript_lines = []
    for line in lines:
        # Skip header, footer, and existing summary
        if line.startswith("[") and "]" in line:
            # This is a timestamped transcript line
            transcript_lines.append(line.split("]", 1)[1].strip())
        elif line.strip() and not any(
            line.startswith(x)
            for x in ["Transcript ", "Audio device:", "Model:", "---", "##", "Duration:", "**"]
        ):
            # Include other content lines that aren't metadata
            if not line.startswith("-"):  # Skip existing bullet points
                transcript_lines.append(line)

    if not transcript_lines:
        print("❌ No transcript content found in file")
        sys.exit(1)

    transcript_text = " ".join(transcript_lines)
    print(f"   Found {len(transcript_lines)} transcript segments")

    print("\n🤖 Generating summary...")
    summary = summarize_transcript(transcript_text)

    if summary:
        print("\n" + "=" * 60)
        print("📋 Meeting Summary:")
        print("=" * 60)
        print(summary)

        # Ask if user wants to append to the file
        print("\n" + "=" * 60)
        choice = input("💾 Append summary to transcript file? (Y/n): ").strip().lower()
        if choice in ["", "y", "yes"]:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write("\n---\n")
                f.write("## Meeting Summary\n\n")
                f.write(summary)
                f.write("\n")
            print(f"✅ Summary appended to: {filepath}")
        else:
            print("   Summary not saved to file")
    else:
        print("❌ Failed to generate summary")
        sys.exit(1)


def chat_with_transcript(filepath: str) -> None:
    """Start an interactive chat session with a transcript."""
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        sys.exit(1)

    print(f"📄 Loading transcript: {filepath}")

    with open(filepath, encoding="utf-8") as f:
        transcript_content = f.read()

    # Initialize Bedrock client
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    # System prompt with transcript context
    system_prompt = f"""You are a helpful assistant that answers questions about a meeting transcript.
You have access to the full transcript below. Answer questions accurately based on what was discussed.
If something wasn't mentioned in the meeting, say so.

=== MEETING TRANSCRIPT ===
{transcript_content}
=== END TRANSCRIPT ==="""

    # Conversation history for multi-turn chat
    messages: list[dict[str, str]] = []

    print("\n" + "=" * 60)
    print("💬 Chat with Meeting Transcript")
    print("=" * 60)
    print("Ask questions about the meeting. Type 'quit' or 'exit' to end.")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n🧑 You: ").strip()

            if user_input.lower() in ["quit", "exit", "q"]:
                print("\n👋 Ending chat session. Goodbye!")
                break

            if not user_input:
                continue

            # Add user message to history
            messages.append({"role": "user", "content": user_input})

            print("\n🤖 Assistant: ", end="", flush=True)

            # Call Bedrock
            response = bedrock.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 1024,
                        "system": system_prompt,
                        "messages": messages,
                    }
                ),
            )

            result = json.loads(response["body"].read())
            assistant_message = result["content"][0]["text"]

            # Add assistant response to history
            messages.append({"role": "assistant", "content": assistant_message})

            print(assistant_message)

        except KeyboardInterrupt:
            print("\n\n👋 Ending chat session. Goodbye!")
            break
        except Exception as e:
            print(f"\n⚠️  Error: {e}")
            # Remove the failed user message from history
            if messages and messages[-1]["role"] == "user":
                messages.pop()


def transcribe_existing_audio(filepath: str) -> None:
    """Transcribe an existing audio file (WAV, MP3, etc.)."""
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        sys.exit(1)

    print("=" * 60)
    print("🎵 Transcribing existing audio file")
    print("=" * 60)
    print(f"   Audio file: {filepath}")
    print()

    # Load Whisper model
    model = load_whisper_model()

    # Transcribe
    print("🔄 Transcribing audio...")
    transcript_text = transcribe_wav_file(model, filepath)

    if transcript_text:
        # Create transcript file
        transcript_path = create_transcript_file()

        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(f"Transcription of: {filepath}\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Model: {WHISPER_MODEL}\n")
            f.write("\n")
            f.write(transcript_text)
            f.write("\n")

        # Display transcript
        print("\n" + "=" * 60)
        print("📝 Transcript:")
        print("=" * 60)
        print(transcript_text)

        # Generate summary
        print("\n🤖 Generating meeting summary...")
        plain_text = " ".join(
            line.split("]", 1)[1].strip() if "]" in line else line
            for line in transcript_text.split("\n")
            if line.strip()
        )
        summary = summarize_transcript(plain_text)

        if summary:
            with open(transcript_path, "a", encoding="utf-8") as f:
                f.write("\n---\n")
                f.write("## Meeting Summary\n\n")
                f.write(summary)
                f.write("\n")

            print("\n" + "=" * 60)
            print("📋 Meeting Summary:")
            print("=" * 60)
            print(summary)

        print("\n" + "=" * 60)
        print("✅ Done!")
        print(f"📝 Transcript saved to: {transcript_path}")
        print("=" * 60)
    else:
        print("❌ No speech detected in audio file")
        sys.exit(1)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Audio recording and transcription with meeting summarization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python transcribe_live.py                        # Record and transcribe
  python transcribe_live.py --transcribe-audio F   # Transcribe existing audio file
  python transcribe_live.py --summarize FILE       # Summarize existing transcript
  python transcribe_live.py --chat FILE            # Chat with a transcript
        """,
    )
    parser.add_argument(
        "--transcribe-audio",
        metavar="FILE",
        help="Transcribe an existing audio file (WAV, MP3, etc.) instead of recording",
    )
    parser.add_argument(
        "--summarize",
        metavar="FILE",
        help="Summarize an existing transcript file instead of recording",
    )
    parser.add_argument(
        "--chat",
        metavar="FILE",
        help="Start interactive chat with a transcript file",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.chat:
        chat_with_transcript(args.chat)
    elif args.transcribe_audio:
        transcribe_existing_audio(args.transcribe_audio)
    elif args.summarize:
        summarize_existing_file(args.summarize)
    else:
        main()
