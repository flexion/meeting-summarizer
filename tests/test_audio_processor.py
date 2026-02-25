"""Tests for playwright_bot/audio/processor.py."""

import wave

import numpy as np

from playwright_bot.audio.processor import AudioProcessor, convert_audio_chunk


class TestConvertAudioChunk:
    """Tests for the standalone convert_audio_chunk() function."""

    def test_empty_input_returns_empty_bytes(self):
        result = convert_audio_chunk(b"")
        assert result == b""

    def test_stereo_to_mono_averaging(self):
        # Create stereo float32: L=0.5, R=-0.5 -> mono should be 0.0
        # Use same rate to avoid resampling
        left = 0.5
        right = -0.5
        stereo = np.array([left, right], dtype=np.float32)
        result = convert_audio_chunk(
            stereo.tobytes(), source_rate=16000, target_rate=16000, source_channels=2
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert len(output) == 1
        assert output[0] == 0  # (0.5 + -0.5) / 2 = 0

    def test_stereo_to_mono_values(self):
        # L=0.4, R=0.6 -> mono = 0.5
        stereo = np.array([0.4, 0.6, 0.4, 0.6], dtype=np.float32)
        result = convert_audio_chunk(
            stereo.tobytes(), source_rate=16000, target_rate=16000, source_channels=2
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert len(output) == 2
        expected = int(0.5 * 32767)
        assert abs(output[0] - expected) < 2

    def test_mono_passthrough(self):
        mono = np.array([0.5, -0.5, 0.25], dtype=np.float32)
        result = convert_audio_chunk(
            mono.tobytes(), source_rate=16000, target_rate=16000, source_channels=1
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert len(output) == 3

    def test_resampling_output_length(self):
        # 48kHz mono -> 16kHz mono: output should be ~1/3 the input length
        num_samples = 4800  # 100ms at 48kHz
        mono = np.zeros(num_samples, dtype=np.float32)
        result = convert_audio_chunk(
            mono.tobytes(), source_rate=48000, target_rate=16000, source_channels=1
        )
        output = np.frombuffer(result, dtype=np.int16)
        expected_len = int(num_samples * 16000 / 48000)
        assert output.shape[0] == expected_len

    def test_clipping_above_one(self):
        # Values > 1.0 should be clipped
        loud = np.array([2.0], dtype=np.float32)
        result = convert_audio_chunk(
            loud.tobytes(), source_rate=16000, target_rate=16000, source_channels=1
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert output[0] == 32767  # Clipped to max int16

    def test_clipping_below_negative_one(self):
        loud = np.array([-2.0], dtype=np.float32)
        result = convert_audio_chunk(
            loud.tobytes(), source_rate=16000, target_rate=16000, source_channels=1
        )
        output = np.frombuffer(result, dtype=np.int16)
        assert output[0] == -32767  # Clipped to min (32767 * -1)


class TestAudioProcessorResample:
    """Tests for AudioProcessor._resample()."""

    def test_same_rate_returns_unchanged(self):
        proc = AudioProcessor()
        audio = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        result = proc._resample(audio, 16000, 16000)
        np.testing.assert_array_equal(result, audio)

    def test_downsample_output_length(self):
        proc = AudioProcessor()
        audio = np.random.rand(4800).astype(np.float32)
        result = proc._resample(audio, 48000, 16000)
        expected_len = int(4800 * 16000 / 48000)
        assert len(result) == expected_len

    def test_empty_input(self):
        proc = AudioProcessor()
        audio = np.array([], dtype=np.float32)
        result = proc._resample(audio, 48000, 16000)
        assert len(result) == 0


class TestAudioProcessorDuration:
    """Tests for AudioProcessor.duration property."""

    def test_zero_samples(self):
        proc = AudioProcessor()
        assert proc.duration == 0.0

    def test_duration_calculation(self):
        proc = AudioProcessor(target_rate=16000)
        proc._total_samples = 16000
        assert proc.duration == 1.0

    def test_duration_half_second(self):
        proc = AudioProcessor(target_rate=16000)
        proc._total_samples = 8000
        assert proc.duration == 0.5


class TestAudioProcessorStartStop:
    """Tests for AudioProcessor start/stop lifecycle."""

    def test_start_creates_wav_file(self, tmp_path):
        proc = AudioProcessor(output_dir=str(tmp_path))
        wav_path = proc.start()
        assert wav_path is not None
        assert wav_path.endswith(".wav")
        assert proc.is_processing is True

        proc.stop()
        assert proc.is_processing is False

        # Verify WAV file exists and is valid
        with wave.open(wav_path, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000

    def test_stop_returns_path_and_duration(self, tmp_path):
        proc = AudioProcessor(output_dir=str(tmp_path))
        proc.start()
        result = proc.stop()
        assert result is not None
        path, duration = result
        assert path.endswith(".wav")
        assert duration == 0.0

    def test_stop_when_not_started_returns_none(self):
        proc = AudioProcessor()
        assert proc.stop() is None


class TestAudioProcessorProcess:
    """Tests for AudioProcessor.process()."""

    def test_process_writes_audio(self, tmp_path):
        proc = AudioProcessor(output_dir=str(tmp_path))
        proc.start()

        # Create mono float32 audio at 16kHz (no resampling needed)
        samples = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        proc.process(samples.tobytes(), source_rate=16000, source_channels=1)

        assert proc.total_samples == 4

        result = proc.stop()
        path, duration = result
        assert duration > 0

        # Verify audio was written to file
        with wave.open(path, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            output = np.frombuffer(frames, dtype=np.int16)
            assert len(output) == 4

    def test_process_when_not_started_is_noop(self):
        proc = AudioProcessor()
        samples = np.array([0.1], dtype=np.float32)
        # Should not raise
        proc.process(samples.tobytes(), source_rate=16000, source_channels=1)
