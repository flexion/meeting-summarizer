"""Audio capture from browser using Web Audio API injection."""

from __future__ import annotations

import base64
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from playwright_bot.audio.exceptions import AudioCaptureError

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# JavaScript code to inject for audio capture
AUDIO_CAPTURE_JS = """
(function() {
    // Prevent double-initialization
    if (window.__audioCaptureState) {
        console.log('[AudioCapture] Already initialized');
        return { success: true, alreadyInitialized: true };
    }

    console.log('[AudioCapture] Initializing audio capture...');

    // State management
    window.__audioCaptureState = {
        capturing: false,
        audioContext: null,
        processors: [],
        buffer: [],
        bufferSize: 4096,
        flushThreshold: 16384,  // Flush every ~1 second at 48kHz
        sampleRate: 48000,
        capturedElements: new WeakSet()
    };

    const state = window.__audioCaptureState;

    // Function to flush buffer to Python
    function flushBuffer() {
        if (state.buffer.length === 0) return;

        try {
            // Interleave stereo channels: [L0, R0, L1, R1, ...]
            const totalSamples = state.buffer.reduce((sum, chunk) => sum + chunk.left.length, 0);
            const interleaved = new Float32Array(totalSamples * 2);

            let offset = 0;
            for (const chunk of state.buffer) {
                for (let i = 0; i < chunk.left.length; i++) {
                    interleaved[offset++] = chunk.left[i];
                    interleaved[offset++] = chunk.right[i];
                }
            }

            // Convert to base64
            const bytes = new Uint8Array(interleaved.buffer);
            let binary = '';
            const chunkSize = 8192;
            for (let i = 0; i < bytes.length; i += chunkSize) {
                binary += String.fromCharCode.apply(null, bytes.slice(i, i + chunkSize));
            }
            const base64Data = btoa(binary);

            // Send to Python via exposed function
            if (typeof window.__receiveAudioData === 'function') {
                window.__receiveAudioData(base64Data, state.sampleRate, 2);
            }

            // Clear buffer
            state.buffer = [];
        } catch (e) {
            console.error('[AudioCapture] Error flushing buffer:', e);
        }
    }

    // Function to capture audio from a media element
    function captureMediaElement(element) {
        if (!state.capturing || state.capturedElements.has(element)) {
            return;
        }

        try {
            console.log('[AudioCapture] Capturing media element:', element.tagName, element.src || element.srcObject);

            // Create AudioContext if needed
            if (!state.audioContext) {
                state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
                state.sampleRate = state.audioContext.sampleRate;
                console.log('[AudioCapture] AudioContext created, sample rate:', state.sampleRate);
            }

            // Create source from media element
            const source = state.audioContext.createMediaElementSource(element);

            // Create ScriptProcessor for capturing audio data
            const processor = state.audioContext.createScriptProcessor(state.bufferSize, 2, 2);

            processor.onaudioprocess = function(e) {
                if (!state.capturing) return;

                const left = new Float32Array(e.inputBuffer.getChannelData(0));
                const right = new Float32Array(e.inputBuffer.getChannelData(1));

                state.buffer.push({ left, right });

                // Check if we should flush
                const totalSamples = state.buffer.reduce((sum, chunk) => sum + chunk.left.length, 0);
                if (totalSamples >= state.flushThreshold) {
                    flushBuffer();
                }
            };

            // Connect: source -> processor -> destination (so audio still plays)
            source.connect(processor);
            processor.connect(state.audioContext.destination);

            state.processors.push({ source, processor, element });
            state.capturedElements.add(element);

            console.log('[AudioCapture] Media element captured successfully');
        } catch (e) {
            console.error('[AudioCapture] Error capturing media element:', e);
        }
    }

    // Function to capture audio from a MediaStream (WebRTC)
    function captureMediaStream(stream) {
        if (!state.capturing) return;

        try {
            const audioTracks = stream.getAudioTracks();
            if (audioTracks.length === 0) {
                console.log('[AudioCapture] Stream has no audio tracks');
                return;
            }

            console.log('[AudioCapture] Capturing MediaStream with', audioTracks.length, 'audio track(s)');

            // Create AudioContext if needed
            if (!state.audioContext) {
                state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
                state.sampleRate = state.audioContext.sampleRate;
                console.log('[AudioCapture] AudioContext created, sample rate:', state.sampleRate);
            }

            // Create source from stream
            const source = state.audioContext.createMediaStreamSource(stream);

            // Create ScriptProcessor for capturing audio data
            const processor = state.audioContext.createScriptProcessor(state.bufferSize, 2, 2);

            processor.onaudioprocess = function(e) {
                if (!state.capturing) return;

                const left = new Float32Array(e.inputBuffer.getChannelData(0));
                // Handle mono streams
                const right = e.inputBuffer.numberOfChannels > 1
                    ? new Float32Array(e.inputBuffer.getChannelData(1))
                    : new Float32Array(left);

                state.buffer.push({ left, right });

                // Check if we should flush
                const totalSamples = state.buffer.reduce((sum, chunk) => sum + chunk.left.length, 0);
                if (totalSamples >= state.flushThreshold) {
                    flushBuffer();
                }
            };

            // Connect: source -> processor (no destination to avoid feedback)
            source.connect(processor);
            // Connect to a silent gain node to keep processing active
            const silentGain = state.audioContext.createGain();
            silentGain.gain.value = 0;
            processor.connect(silentGain);
            silentGain.connect(state.audioContext.destination);

            state.processors.push({ source, processor, stream });

            console.log('[AudioCapture] MediaStream captured successfully');
        } catch (e) {
            console.error('[AudioCapture] Error capturing MediaStream:', e);
        }
    }

    // Hook HTMLMediaElement.prototype.play to intercept audio/video elements
    const originalPlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function() {
        if (state.capturing && !state.capturedElements.has(this)) {
            // Delay capture slightly to ensure element is ready
            setTimeout(() => captureMediaElement(this), 100);
        }
        return originalPlay.apply(this, arguments);
    };

    // Hook RTCPeerConnection to intercept WebRTC streams (for Zoom)
    if (window.RTCPeerConnection) {
        const originalAddTrack = RTCPeerConnection.prototype.addTrack;
        RTCPeerConnection.prototype.addTrack = function(track, ...streams) {
            console.log('[AudioCapture] RTCPeerConnection.addTrack called:', track.kind);
            return originalAddTrack.apply(this, [track, ...streams]);
        };

        const originalOnTrack = Object.getOwnPropertyDescriptor(RTCPeerConnection.prototype, 'ontrack');
        Object.defineProperty(RTCPeerConnection.prototype, 'ontrack', {
            set: function(handler) {
                const wrappedHandler = function(event) {
                    console.log('[AudioCapture] RTCPeerConnection ontrack event:', event.track.kind);
                    if (state.capturing && event.track.kind === 'audio') {
                        // Capture the stream containing this audio track
                        if (event.streams && event.streams.length > 0) {
                            captureMediaStream(event.streams[0]);
                        }
                    }
                    if (handler) {
                        return handler.call(this, event);
                    }
                };
                if (originalOnTrack && originalOnTrack.set) {
                    originalOnTrack.set.call(this, wrappedHandler);
                }
            },
            get: function() {
                if (originalOnTrack && originalOnTrack.get) {
                    return originalOnTrack.get.call(this);
                }
            }
        });
    }

    // Expose functions to control capture
    window.__startAudioCapture = function() {
        console.log('[AudioCapture] Starting capture...');
        state.capturing = true;
        state.buffer = [];

        // Resume AudioContext if suspended
        if (state.audioContext && state.audioContext.state === 'suspended') {
            state.audioContext.resume();
        }

        // Scan for existing media elements and capture them
        document.querySelectorAll('audio, video').forEach(el => {
            if (!el.paused) {
                captureMediaElement(el);
            }
        });

        return true;
    };

    window.__stopAudioCapture = function() {
        console.log('[AudioCapture] Stopping capture...');
        state.capturing = false;

        // Flush any remaining buffer
        flushBuffer();

        // Disconnect processors
        for (const { source, processor } of state.processors) {
            try {
                processor.disconnect();
                source.disconnect();
            } catch (e) {
                // Ignore disconnection errors
            }
        }
        state.processors = [];

        // Close AudioContext
        if (state.audioContext) {
            state.audioContext.close();
            state.audioContext = null;
        }

        console.log('[AudioCapture] Capture stopped');
        return true;
    };

    window.__getAudioCaptureState = function() {
        return {
            capturing: state.capturing,
            sampleRate: state.sampleRate,
            processorCount: state.processors.length,
            bufferSamples: state.buffer.reduce((sum, chunk) => sum + chunk.left.length, 0)
        };
    };

    console.log('[AudioCapture] Initialization complete');
    return { success: true, alreadyInitialized: false };
})();
"""


class AudioCapturer:
    """Captures audio from browser using Web Audio API injection.

    This class injects JavaScript into the browser page to intercept and capture
    audio from media elements and WebRTC streams. The captured audio is sent
    back to Python via an exposed function.

    Usage:
        capturer = AudioCapturer(page, on_audio_data=my_callback)
        capturer.start()
        # ... wait for audio ...
        capturer.stop()
    """

    def __init__(
        self,
        page: Page,
        on_audio_data: Callable[[bytes, int, int], None] | None = None,
        buffer_size: int = 4096,
    ) -> None:
        """Initialize the audio capturer.

        Args:
            page: Playwright page instance
            on_audio_data: Callback function(audio_bytes, sample_rate, channels)
            buffer_size: Audio buffer size in samples
        """
        self._page = page
        self._on_audio_data = on_audio_data
        self._buffer_size = buffer_size
        self._capturing = False
        self._sample_rate = 48000  # Default, updated from browser
        self._initialized = False
        self._lock = threading.Lock()
        self._total_samples_received = 0

    def _receive_audio_data(self, base64_data: str, sample_rate: int, channels: int) -> None:
        """Callback function exposed to JavaScript for receiving audio data.

        Args:
            base64_data: Base64-encoded Float32Array audio data
            sample_rate: Sample rate of the audio
            channels: Number of audio channels
        """
        if not self._capturing:
            return

        try:
            # Decode base64 to bytes
            audio_bytes = base64.b64decode(base64_data)

            # Update sample rate if changed
            with self._lock:
                self._sample_rate = sample_rate
                # Calculate samples (float32 = 4 bytes per sample, stereo = 2 channels)
                num_samples = len(audio_bytes) // (4 * channels)
                self._total_samples_received += num_samples

            # Forward to callback
            if self._on_audio_data:
                self._on_audio_data(audio_bytes, sample_rate, channels)

        except Exception as e:
            logger.error(f"Error receiving audio data: {e}")

    def _initialize(self) -> bool:
        """Initialize audio capture by injecting JavaScript.

        Returns:
            True if initialization was successful
        """
        if self._initialized:
            return True

        try:
            # Expose Python callback to JavaScript
            self._page.expose_function("__receiveAudioData", self._receive_audio_data)
            logger.info("Exposed __receiveAudioData function to browser")
        except Exception as e:
            # Function may already be exposed
            if "has been already registered" not in str(e):
                logger.warning(f"Could not expose function: {e}")

        try:
            # Inject the audio capture JavaScript
            result = self._page.evaluate(AUDIO_CAPTURE_JS)

            if result and result.get("success"):
                self._initialized = True
                if result.get("alreadyInitialized"):
                    logger.info("Audio capture was already initialized")
                else:
                    logger.info("Audio capture JavaScript injected successfully")
                return True
            else:
                logger.error("Failed to inject audio capture JavaScript")
                return False

        except Exception as e:
            logger.error(f"Error initializing audio capture: {e}")
            raise AudioCaptureError(f"Failed to initialize audio capture: {e}") from e

    def start(self) -> bool:
        """Start capturing audio from the browser.

        Returns:
            True if capture started successfully

        Raises:
            AudioCaptureError: If capture fails to start
        """
        if self._capturing:
            logger.warning("Audio capture already running")
            return True

        # Initialize if needed
        if not self._initialize():
            raise AudioCaptureError("Failed to initialize audio capture")

        try:
            # Start capture in JavaScript
            result = self._page.evaluate("window.__startAudioCapture()")

            if result:
                self._capturing = True
                self._total_samples_received = 0
                logger.info("Audio capture started")
                return True
            else:
                raise AudioCaptureError("JavaScript __startAudioCapture returned false")

        except Exception as e:
            logger.error(f"Error starting audio capture: {e}")
            raise AudioCaptureError(f"Failed to start audio capture: {e}") from e

    def stop(self) -> None:
        """Stop capturing audio."""
        if not self._capturing:
            return

        try:
            # Stop capture in JavaScript
            self._page.evaluate("window.__stopAudioCapture()")
            logger.info("Audio capture stopped")
        except Exception as e:
            logger.warning(f"Error stopping audio capture: {e}")
        finally:
            self._capturing = False

    def get_sample_rate(self) -> int:
        """Get the current sample rate of captured audio.

        Returns:
            Sample rate in Hz
        """
        with self._lock:
            return self._sample_rate

    def get_capture_state(self) -> dict:
        """Get the current capture state from JavaScript.

        Returns:
            Dictionary with capture state information
        """
        if not self._initialized:
            return {
                "capturing": False,
                "sampleRate": self._sample_rate,
                "processorCount": 0,
                "bufferSamples": 0,
            }

        try:
            return self._page.evaluate("window.__getAudioCaptureState()")
        except Exception as e:
            logger.warning(f"Error getting capture state: {e}")
            return {
                "capturing": self._capturing,
                "sampleRate": self._sample_rate,
                "processorCount": 0,
                "bufferSamples": 0,
            }

    def is_capturing(self) -> bool:
        """Check if audio capture is currently running.

        Returns:
            True if capturing
        """
        return self._capturing

    def get_total_samples_received(self) -> int:
        """Get the total number of audio samples received.

        Returns:
            Total samples received since capture started
        """
        with self._lock:
            return self._total_samples_received

    def get_duration_seconds(self) -> float:
        """Get the duration of captured audio in seconds.

        Returns:
            Duration in seconds
        """
        with self._lock:
            if self._sample_rate > 0:
                return self._total_samples_received / self._sample_rate
            return 0.0
