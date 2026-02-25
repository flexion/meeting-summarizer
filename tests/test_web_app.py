"""Tests for web_app.py TranscriptionState, ConnectionManager, and standalone functions."""

import os
from datetime import datetime
from queue import Queue
from unittest.mock import MagicMock, patch

from web_app import (
    ConnectionManager,
    TranscriptionState,
    get_audio_devices,
    load_model,
    transcribe_wav_file_streaming,
)


class TestTranscriptionStateTranscript:
    """Tests for TranscriptionState transcript management."""

    def test_add_and_get_transcript(self, transcription_state):
        transcription_state.add_transcript("[00:01]", "Hello everyone")
        transcription_state.add_transcript("[00:15]", "Welcome to the meeting")

        result = transcription_state.get_transcript_text()
        assert "[00:01] Hello everyone" in result
        assert "[00:15] Welcome to the meeting" in result

    def test_get_transcript_text_empty(self, transcription_state):
        assert transcription_state.get_transcript_text() == ""

    def test_multiple_segments_joined_with_newlines(self, transcription_state):
        transcription_state.add_transcript("[00:01]", "Line one")
        transcription_state.add_transcript("[00:02]", "Line two")

        result = transcription_state.get_transcript_text()
        lines = result.split("\n")
        assert len(lines) == 2


class TestTranscriptionStateStatus:
    """Tests for TranscriptionState.get_status()."""

    def test_idle_status(self, transcription_state):
        status = transcription_state.get_status()
        assert status["running"] is False
        assert status["transcribing"] is False
        assert status["device"] == ""
        assert status["elapsed_seconds"] == 0
        assert status["has_transcript"] is False
        assert status["loaded_file"] is None
        assert status["wav_path"] is None

    def test_status_has_transcript_after_add(self, transcription_state):
        transcription_state.add_transcript("[00:01]", "text")
        status = transcription_state.get_status()
        assert status["has_transcript"] is True

    def test_status_transcribing_flag(self, transcription_state):
        transcription_state.set_transcribing(True)
        status = transcription_state.get_status()
        assert status["transcribing"] is True

        transcription_state.set_transcribing(False)
        status = transcription_state.get_status()
        assert status["transcribing"] is False


class TestTranscriptionStateClear:
    """Tests for clear methods."""

    def test_clear_chat_history(self, transcription_state):
        transcription_state.chat_history.append({"role": "user", "content": "hello"})
        transcription_state.clear_chat_history()
        assert transcription_state.chat_history == []

    def test_clear_loaded_transcript(self, transcription_state):
        transcription_state.add_transcript("[00:01]", "text")
        transcription_state.chat_history.append({"role": "user", "content": "q"})
        transcription_state.clear_loaded_transcript()
        assert transcription_state.transcript_segments == []
        assert transcription_state.chat_history == []


class TestTranscriptionStateLoadFile:
    """Tests for load_transcript_file()."""

    def test_load_valid_transcript(self, tmp_path, transcription_state, sample_transcript_content):
        filepath = tmp_path / "transcript.txt"
        filepath.write_text(sample_transcript_content)

        result = transcription_state.load_transcript_file(str(filepath))
        assert result is True
        assert len(transcription_state.transcript_segments) == 3

        text = transcription_state.get_transcript_text()
        assert "Hello everyone" in text
        assert "project roadmap" in text

    def test_load_file_no_transcript_lines(self, tmp_path, transcription_state):
        filepath = tmp_path / "empty_transcript.txt"
        filepath.write_text("Some header\nNo timestamps here\nJust plain text\n")

        result = transcription_state.load_transcript_file(str(filepath))
        assert result is False
        assert len(transcription_state.transcript_segments) == 0

    def test_load_nonexistent_file(self, transcription_state):
        result = transcription_state.load_transcript_file("/nonexistent/file.txt")
        assert result is False

    def test_load_clears_previous_data(
        self, tmp_path, transcription_state, sample_transcript_content
    ):
        # Add existing data
        transcription_state.add_transcript("[99:99]", "old data")
        transcription_state.chat_history.append({"role": "user", "content": "old"})

        filepath = tmp_path / "transcript.txt"
        filepath.write_text(sample_transcript_content)
        transcription_state.load_transcript_file(str(filepath))

        # Old data should be gone
        text = transcription_state.get_transcript_text()
        assert "old data" not in text
        assert transcription_state.chat_history == []


class TestConnectionManager:
    """Tests for ConnectionManager."""

    def test_disconnect_removes_websocket(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.active_connections.add(ws)
        assert ws in mgr.active_connections

        mgr.disconnect(ws)
        assert ws not in mgr.active_connections

    def test_disconnect_nonexistent_websocket_no_error(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        # Should not raise
        mgr.disconnect(ws)
        assert len(mgr.active_connections) == 0


class TestTranscriptionStateStart:
    """Tests for TranscriptionState.start()."""

    def test_start_creates_wav_and_sets_state(self, tmp_path):
        state = TranscriptionState()
        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("BlackHole 2ch")

        assert state.running is True
        assert state.transcribing is False
        assert state.device_name == "BlackHole 2ch"
        assert state.start_time is not None
        assert state.end_time is None
        assert state.total_frames == 0
        assert state.wav_file is not None
        assert os.path.exists(state.wav_path)

        # Clean up
        state.wav_file.close()

    def test_start_clears_previous_segments(self, tmp_path):
        state = TranscriptionState()
        state.transcript_segments = [{"timestamp": "[00:01]", "text": "old"}]
        state.chat_history = [{"role": "user", "content": "old"}]

        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("Test Device")

        assert state.transcript_segments == []
        assert state.chat_history == []

        # Clean up
        state.wav_file.close()


class TestTranscriptionStateStopRecording:
    """Tests for TranscriptionState.stop_recording()."""

    def test_stop_recording_closes_wav(self, tmp_path):
        state = TranscriptionState()
        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("Test Device")
            wav_path = state.stop_recording()

        assert state.running is False
        assert state.end_time is not None
        assert state.wav_file is None
        assert wav_path.endswith(".wav")

    def test_stop_recording_returns_wav_path(self, tmp_path):
        state = TranscriptionState()
        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("Test Device")
            expected_path = state.wav_path
            result = state.stop_recording()

        assert result == expected_path


class TestTranscriptionStateWriteAudioFrame:
    """Tests for TranscriptionState.write_audio_frame()."""

    def test_write_increments_total_frames(self, tmp_path):
        state = TranscriptionState()
        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("Test Device")
            # 16-bit = 2 bytes per sample; 100 bytes = 50 samples
            state.write_audio_frame(b"\x00" * 100)
            assert state.total_frames == 50

            state.write_audio_frame(b"\x00" * 200)
            assert state.total_frames == 150

        state.wav_file.close()

    def test_write_when_not_started_is_noop(self):
        state = TranscriptionState()
        # Should not raise
        state.write_audio_frame(b"\x00" * 100)
        assert state.total_frames == 0


class TestTranscriptionStateIsRunning:
    """Tests for TranscriptionState.is_running()."""

    def test_not_running_initially(self):
        state = TranscriptionState()
        assert state.is_running() is False

    def test_running_after_start(self, tmp_path):
        state = TranscriptionState()
        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("Test")
        assert state.is_running() is True
        state.wav_file.close()

    def test_not_running_after_stop(self, tmp_path):
        state = TranscriptionState()
        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("Test")
            state.stop_recording()
        assert state.is_running() is False


class TestTranscriptionStateGetStatusRunning:
    """Tests for get_status() when running/stopped."""

    def test_status_running_has_elapsed(self, tmp_path):
        state = TranscriptionState()
        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("Test Device")

        status = state.get_status()
        assert status["running"] is True
        assert status["elapsed_seconds"] >= 0
        assert status["device"] == "Test Device"
        assert status["wav_path"] is not None

        state.wav_file.close()

    def test_status_after_stop_has_elapsed(self, tmp_path):
        state = TranscriptionState()
        with patch("web_app.OUTPUT_DIR", str(tmp_path)):
            state.start("Test Device")
            # Manually set start time to the past for a nonzero elapsed
            state.start_time = datetime(2026, 1, 1, 10, 0, 0)
            state.end_time = datetime(2026, 1, 1, 10, 0, 5)
            state.running = False

        status = state.get_status()
        assert status["running"] is False
        assert status["elapsed_seconds"] == 5


class TestGetAudioDevices:
    """Tests for get_audio_devices() standalone function."""

    @patch("web_app.pyaudio.PyAudio")
    def test_filters_input_devices(self, mock_pyaudio_cls):
        mock_pa = MagicMock()
        mock_pyaudio_cls.return_value = mock_pa
        mock_pa.get_device_count.return_value = 3
        mock_pa.get_device_info_by_index.side_effect = [
            {"name": "Built-in Mic", "maxInputChannels": 1, "maxOutputChannels": 0},
            {"name": "Speakers", "maxInputChannels": 0, "maxOutputChannels": 2},
            {"name": "BlackHole 2ch", "maxInputChannels": 2, "maxOutputChannels": 2},
        ]

        devices = get_audio_devices()
        # "Speakers" has no input and is not aggregate/blackhole, should be excluded
        names = [d["name"] for d in devices]
        assert "Built-in Mic" in names
        assert "BlackHole 2ch" in names
        assert "Speakers" not in names
        mock_pa.terminate.assert_called_once()

    @patch("web_app.pyaudio.PyAudio")
    def test_includes_aggregate_devices(self, mock_pyaudio_cls):
        mock_pa = MagicMock()
        mock_pyaudio_cls.return_value = mock_pa
        mock_pa.get_device_count.return_value = 1
        mock_pa.get_device_info_by_index.side_effect = [
            {"name": "Aggregate Device", "maxInputChannels": 0, "maxOutputChannels": 2},
        ]

        devices = get_audio_devices()
        assert len(devices) == 1
        assert devices[0]["is_aggregate"] is True

    @patch("web_app.pyaudio.PyAudio")
    def test_blackhole_flag(self, mock_pyaudio_cls):
        mock_pa = MagicMock()
        mock_pyaudio_cls.return_value = mock_pa
        mock_pa.get_device_count.return_value = 1
        mock_pa.get_device_info_by_index.side_effect = [
            {"name": "BlackHole 2ch", "maxInputChannels": 2, "maxOutputChannels": 2},
        ]

        devices = get_audio_devices()
        assert devices[0]["is_blackhole"] is True


class TestLoadModel:
    """Tests for load_model() standalone function."""

    @patch("web_app.WhisperModel")
    def test_loads_model_on_first_call(self, mock_whisper_cls):
        mock_model = MagicMock()
        mock_whisper_cls.return_value = mock_model

        from web_app import state

        original_model = state.model
        state.model = None
        try:
            result = load_model()
            assert result is mock_model
            mock_whisper_cls.assert_called_once()
        finally:
            state.model = original_model

    @patch("web_app.WhisperModel")
    def test_caches_model(self, mock_whisper_cls):
        mock_model = MagicMock()

        from web_app import state

        original_model = state.model
        state.model = mock_model
        try:
            result = load_model()
            assert result is mock_model
            mock_whisper_cls.assert_not_called()
        finally:
            state.model = original_model


class TestTranscribeWavFileStreaming:
    """Tests for transcribe_wav_file_streaming()."""

    def test_successful_transcription_sends_progress(self):
        mock_model = MagicMock()
        mock_info = MagicMock()

        seg1 = MagicMock()
        seg1.text = " Hello "
        seg1.start = 0.0
        seg1.end = 2.5

        seg2 = MagicMock()
        seg2.text = " World "
        seg2.start = 3.0
        seg2.end = 5.0

        mock_model.transcribe.return_value = ([seg1, seg2], mock_info)

        queue = Queue()
        result = transcribe_wav_file_streaming(mock_model, "/fake/audio.wav", 10.0, queue)

        assert len(result) == 2
        assert result[0]["text"] == "Hello"
        assert result[1]["text"] == "World"

        # Queue should have progress + done messages
        messages = []
        while not queue.empty():
            messages.append(queue.get())

        types = [m["type"] for m in messages]
        assert "progress" in types
        assert "done" in types

    def test_exception_sends_error(self):
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("transcription failed")

        queue = Queue()
        result = transcribe_wav_file_streaming(mock_model, "/fake/audio.wav", 10.0, queue)

        assert result == []

        messages = []
        while not queue.empty():
            messages.append(queue.get())

        types = [m["type"] for m in messages]
        assert "error" in types
        assert "done" in types

    def test_empty_text_segments_skipped(self):
        mock_model = MagicMock()
        mock_info = MagicMock()

        seg_empty = MagicMock()
        seg_empty.text = "   "
        seg_empty.start = 0.0
        seg_empty.end = 1.0

        seg_valid = MagicMock()
        seg_valid.text = " Valid "
        seg_valid.start = 2.0
        seg_valid.end = 3.0

        mock_model.transcribe.return_value = ([seg_empty, seg_valid], mock_info)

        queue = Queue()
        result = transcribe_wav_file_streaming(mock_model, "/fake/audio.wav", 5.0, queue)

        assert len(result) == 1
        assert result[0]["text"] == "Valid"
