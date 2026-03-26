"""Tests for transcribe_live.py core functions."""

import json
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np

from bedrock_utils import summarize_transcript
from transcribe_live import (
    create_transcript_file,
    create_wav_file,
    format_duration,
    format_elapsed_time,
    list_audio_devices,
    parse_args,
    transcribe_audio_buffer,
    transcribe_wav_file,
)


class TestFormatDuration:
    """Tests for format_duration()."""

    def test_sub_hour_duration(self):
        start = datetime(2026, 1, 15, 10, 0, 0)
        end = datetime(2026, 1, 15, 10, 5, 30)
        assert format_duration(start, end) == "5:30"

    def test_exactly_one_hour(self):
        start = datetime(2026, 1, 15, 10, 0, 0)
        end = datetime(2026, 1, 15, 11, 0, 0)
        assert format_duration(start, end) == "1:00:00"

    def test_multi_hour_duration(self):
        start = datetime(2026, 1, 15, 10, 0, 0)
        end = datetime(2026, 1, 15, 11, 5, 30)
        assert format_duration(start, end) == "1:05:30"

    def test_zero_duration(self):
        start = datetime(2026, 1, 15, 10, 0, 0)
        assert format_duration(start, start) == "0:00"

    def test_seconds_only(self):
        start = datetime(2026, 1, 15, 10, 0, 0)
        end = datetime(2026, 1, 15, 10, 0, 45)
        assert format_duration(start, end) == "0:45"

    def test_minutes_pad_with_zero(self):
        start = datetime(2026, 1, 15, 10, 0, 0)
        end = datetime(2026, 1, 15, 11, 3, 5)
        assert format_duration(start, end) == "1:03:05"

    def test_sub_hour_minutes_no_leading_zero(self):
        start = datetime(2026, 1, 15, 10, 0, 0)
        end = datetime(2026, 1, 15, 10, 30, 0)
        assert format_duration(start, end) == "30:00"


class TestFormatElapsedTime:
    """Tests for format_elapsed_time()."""

    @patch("transcribe_live.datetime")
    def test_basic_elapsed(self, mock_datetime):
        start = datetime(2026, 1, 15, 10, 0, 0)
        mock_datetime.now.return_value = datetime(2026, 1, 15, 10, 5, 30)
        # datetime.now() - start_time uses real subtraction
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = format_elapsed_time(start)
        assert result == "[00:05:30]"

    @patch("transcribe_live.datetime")
    def test_zero_elapsed(self, mock_datetime):
        start = datetime(2026, 1, 15, 10, 0, 0)
        mock_datetime.now.return_value = datetime(2026, 1, 15, 10, 0, 0)
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = format_elapsed_time(start)
        assert result == "[00:00:00]"

    @patch("transcribe_live.datetime")
    def test_multi_hour_elapsed(self, mock_datetime):
        start = datetime(2026, 1, 15, 10, 0, 0)
        mock_datetime.now.return_value = datetime(2026, 1, 15, 12, 30, 45)
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = format_elapsed_time(start)
        assert result == "[02:30:45]"


class TestSummarizeTranscript:
    """Tests for summarize_transcript()."""

    def test_empty_transcript_returns_none(self):
        assert summarize_transcript("") is None
        assert summarize_transcript("   ") is None

    @patch("bedrock_utils.boto3")
    def test_successful_summarization(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {"content": [{"text": "Summary of the meeting"}]}
        ).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        result = summarize_transcript("Hello everyone, welcome to the meeting.")
        assert result == "Summary of the meeting"
        mock_boto3.client.assert_called_once_with("bedrock-runtime", region_name="us-east-1")

    @patch("bedrock_utils.boto3")
    def test_api_error_returns_none(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.side_effect = Exception("API error")

        result = summarize_transcript("Some transcript text")
        assert result is None


class TestCreateTranscriptFile:
    """Tests for create_transcript_file()."""

    @patch("transcribe_live.datetime")
    @patch("transcribe_live.os.makedirs")
    def test_creates_file_path_with_timestamp(self, mock_makedirs, mock_dt):
        mock_dt.now.return_value = datetime(2026, 3, 15, 14, 30, 45)
        result = create_transcript_file()
        assert result.endswith("transcript_2026-03-15_14-30-45.txt")
        mock_makedirs.assert_called_once()

    @patch("transcribe_live.datetime")
    @patch("transcribe_live.os.makedirs")
    def test_creates_output_dir(self, mock_makedirs, mock_dt):
        mock_dt.now.return_value = datetime(2026, 1, 1, 0, 0, 0)
        create_transcript_file()
        mock_makedirs.assert_called_once_with("transcripts", exist_ok=True)


class TestCreateWavFile:
    """Tests for create_wav_file()."""

    def test_creates_wav_file(self, tmp_path):
        with patch("transcribe_live.OUTPUT_DIR", str(tmp_path)):
            filepath, wf = create_wav_file()
            try:
                assert filepath.endswith(".wav")
                assert "recording_" in filepath
                assert os.path.exists(filepath)
            finally:
                wf.close()

    def test_wav_file_has_correct_params(self, tmp_path):
        with patch("transcribe_live.OUTPUT_DIR", str(tmp_path)):
            filepath, wf = create_wav_file()
            try:
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2
                assert wf.getframerate() == 16000
            finally:
                wf.close()


class TestTranscribeWavFile:
    """Tests for transcribe_wav_file()."""

    @patch("transcribe_live.WhisperModel")
    def test_successful_transcription(self, _mock_class):
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.95

        seg1 = MagicMock()
        seg1.text = " Hello world "
        seg1.start = 5.0

        seg2 = MagicMock()
        seg2.text = " Second segment "
        seg2.start = 65.0

        mock_model.transcribe.return_value = ([seg1, seg2], mock_info)

        result = transcribe_wav_file(mock_model, "/fake/audio.wav")
        assert result is not None
        assert "[00:05] Hello world" in result
        assert "[01:05] Second segment" in result

    @patch("transcribe_live.WhisperModel")
    def test_empty_segments_returns_none(self, _mock_class):
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.90
        mock_model.transcribe.return_value = ([], mock_info)

        result = transcribe_wav_file(mock_model, "/fake/audio.wav")
        assert result is None

    @patch("transcribe_live.WhisperModel")
    def test_exception_returns_none(self, _mock_class):
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("model error")

        result = transcribe_wav_file(mock_model, "/fake/audio.wav")
        assert result is None

    @patch("transcribe_live.WhisperModel")
    def test_hour_timestamp_format(self, _mock_class):
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.95

        seg = MagicMock()
        seg.text = " Long meeting "
        seg.start = 3661.0  # 1h 1m 1s

        mock_model.transcribe.return_value = ([seg], mock_info)

        result = transcribe_wav_file(mock_model, "/fake/audio.wav")
        assert "[01:01:01] Long meeting" in result


class TestParseArgs:
    """Tests for parse_args()."""

    def test_default_args(self):
        with patch.object(sys, "argv", ["transcribe_live.py"]):
            args = parse_args()
            assert args.transcribe_audio is None
            assert args.summarize is None
            assert args.chat is None

    def test_transcribe_audio_arg(self):
        with patch.object(sys, "argv", ["transcribe_live.py", "--transcribe-audio", "audio.wav"]):
            args = parse_args()
            assert args.transcribe_audio == "audio.wav"

    def test_summarize_arg(self):
        with patch.object(sys, "argv", ["transcribe_live.py", "--summarize", "transcript.txt"]):
            args = parse_args()
            assert args.summarize == "transcript.txt"

    def test_chat_arg(self):
        with patch.object(sys, "argv", ["transcribe_live.py", "--chat", "transcript.txt"]):
            args = parse_args()
            assert args.chat == "transcript.txt"


class TestListAudioDevices:
    """Tests for list_audio_devices()."""

    @patch("transcribe_live.pyaudio.PyAudio")
    def test_lists_devices(self, mock_pyaudio_cls):
        mock_pa = MagicMock()
        mock_pyaudio_cls.return_value = mock_pa
        mock_pa.get_device_count.return_value = 2
        mock_pa.get_device_info_by_index.side_effect = [
            {"name": "Built-in Microphone", "maxInputChannels": 1, "maxOutputChannels": 0},
            {"name": "BlackHole 2ch", "maxInputChannels": 2, "maxOutputChannels": 2},
        ]

        devices = list_audio_devices()
        assert len(devices) == 2
        assert devices[1]["name"] == "BlackHole 2ch"
        mock_pa.terminate.assert_called_once()

    @patch("transcribe_live.pyaudio.PyAudio")
    def test_empty_device_list(self, mock_pyaudio_cls):
        mock_pa = MagicMock()
        mock_pyaudio_cls.return_value = mock_pa
        mock_pa.get_device_count.return_value = 0

        devices = list_audio_devices()
        assert devices == []
        mock_pa.terminate.assert_called_once()


class TestTranscribeAudioBuffer:
    """Tests for transcribe_audio_buffer()."""

    def test_successful_transcription(self):
        mock_model = MagicMock()
        mock_info = MagicMock()
        seg = MagicMock()
        seg.text = " hello world "
        mock_model.transcribe.return_value = ([seg], mock_info)

        audio_data = np.array([100, -100, 50], dtype=np.int16)
        result = transcribe_audio_buffer(mock_model, audio_data, 16000)
        assert result == "hello world"

    def test_error_returns_none(self):
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("model error")

        audio_data = np.array([100, -100], dtype=np.int16)
        result = transcribe_audio_buffer(mock_model, audio_data, 16000)
        assert result is None
