#!/usr/bin/env python3
"""
Minimal Zoom Meeting Bot using zoom-meeting-sdk.

Joins Zoom meetings as a participant, captures audio, and streams it
to the transcription server via WebSocket.

Uses PyQt5 for Qt event loop (required for SDK callbacks).
"""

import asyncio
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from queue import Empty, Queue
from typing import Any

import websockets

# Import Zoom SDK
import zoom_meeting_sdk as zoom
from dotenv import load_dotenv
from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtCore import pyqtSignal as Signal
from PyQt5.QtCore import pyqtSlot as Slot

# Qt5 for event loop (using SDK's bundled Qt via LD_PRELOAD)
from PyQt5.QtWidgets import QApplication

# Load environment variables
load_dotenv()

# Configuration
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
BOT_DISPLAY_NAME = os.getenv("BOT_DISPLAY_NAME", "Transcription Bot")
TRANSCRIBER_WS_URL = os.getenv("TRANSCRIBER_WS_URL", "ws://host.docker.internal:8000/zoom-audio")
AUDIO_WS_PORT = int(os.getenv("AUDIO_WS_PORT", "3001"))


class BotState(Enum):
    """Bot lifecycle states."""
    IDLE = "idle"
    INITIALIZING = "initializing"
    AUTHENTICATED = "authenticated"
    JOINING = "joining"
    IN_MEETING = "in_meeting"
    IN_BREAKOUT = "in_breakout"
    LEAVING = "leaving"
    ERROR = "error"


@dataclass
class MeetingInfo:
    """Information about the current meeting."""
    meeting_number: str
    password: str = ""
    topic: str = ""
    joined_at: datetime | None = None
    breakout_room: str | None = None


class AudioCallback(zoom.ZoomSDKAudioRawDataDelegateCallbacks):
    """Callback handler for raw audio data from Zoom."""

    def __init__(self, on_audio: Callable[[bytes], None]):
        super().__init__()
        self._on_audio = on_audio

    def onMixedAudioRawDataReceived(self, data: zoom.AudioRawData) -> None:
        try:
            buffer = data.GetBuffer()
            if buffer and self._on_audio:
                self._on_audio(buffer)
        except Exception as e:
            print(f"[AudioCallback] Error: {e}")

    def onOneWayAudioRawDataReceived(self, data: zoom.AudioRawData, node_id: int) -> None:
        pass


class AuthCallback(zoom.AuthServiceEventCallbacks):
    """Callback handler for authentication events."""

    def __init__(self, on_auth: Callable[[zoom.AuthResult], None]):
        super().__init__()
        self._on_auth = on_auth
        print("[AuthCallback] Initialized")

    def onAuthenticationReturn(self, result: zoom.AuthResult) -> None:
        print(f"[AuthCallback] onAuthenticationReturn called with: {result}")
        if self._on_auth:
            self._on_auth(result)

    def onLoginReturnWithReason(self, ret: zoom.LOGINSTATUS, reason: zoom.LoginFailReason) -> None:
        print(f"[AuthCallback] onLoginReturnWithReason: {ret}, reason: {reason}")

    def onLogout(self) -> None:
        print("[AuthCallback] onLogout called")

    def onZoomIdentityExpired(self) -> None:
        print("[AuthCallback] onZoomIdentityExpired called")

    def onZoomAuthIdentityExpired(self) -> None:
        print("[AuthCallback] onZoomAuthIdentityExpired called")


class MeetingCallback(zoom.MeetingServiceEventCallbacks):
    """Callback handler for meeting events."""

    def __init__(self, on_status: Callable[[zoom.MeetingStatus, int], None]):
        super().__init__()
        self._on_status = on_status

    def onMeetingStatusChanged(self, status: zoom.MeetingStatus, result: int) -> None:
        print(f"[MeetingCallback] Status: {status}, result: {result}")
        if self._on_status:
            self._on_status(status, result)

    def onMeetingStatisticsWarningNotification(self, warning: zoom.StatisticsWarningType) -> None:
        print(f"[MeetingCallback] Stats warning: {warning}")

    def onMeetingParameterNotification(self, param: zoom.MeetingParameter) -> None:
        pass


class ZoomBotController(QObject):
    """Qt-based Zoom Bot controller."""

    join_requested = Signal(str, str, str)
    leave_requested = Signal()

    def __init__(self, audio_queue: Queue) -> None:
        super().__init__()
        self.state = BotState.IDLE
        self.meeting_info: MeetingInfo | None = None
        self.sdk_initialized = False
        self._audio_queue = audio_queue

        self._auth_service: Any = None
        self._meeting_service: Any = None
        self._audio_helper: Any = None

        self._auth_callback: AuthCallback | None = None
        self._meeting_callback: MeetingCallback | None = None
        self._audio_callback: AudioCallback | None = None

        self._join_result: bool | None = None
        self._join_complete = threading.Event()

        self.join_requested.connect(self._handle_join)
        self.leave_requested.connect(self._handle_leave)

    def _update_state(self, new_state: BotState) -> None:
        self.state = new_state
        print(f"[ZoomBot] State: {new_state.value}")

    def _on_auth_result(self, result: zoom.AuthResult) -> None:
        print(f"[ZoomBot] Auth result: {result}")
        if result == zoom.AUTHRET_SUCCESS:
            self._update_state(BotState.AUTHENTICATED)
            self._meeting_service = zoom.CreateMeetingService()
            self._meeting_callback = MeetingCallback(self._on_meeting_status)
            self._meeting_service.SetEvent(self._meeting_callback)
            print("[ZoomBot] Meeting service created")
        else:
            self._update_state(BotState.ERROR)

    def _on_meeting_status(self, status: zoom.MeetingStatus, result: int) -> None:
        print(f"[ZoomBot] Meeting status: {status}, result code: {result}")
        if status == zoom.MEETING_STATUS_INMEETING:
            self._update_state(BotState.IN_MEETING)
            if self.meeting_info:
                self.meeting_info.joined_at = datetime.now()
            self._setup_audio_capture()
            self._join_result = True
            self._join_complete.set()
        elif status == zoom.MEETING_STATUS_JOIN_BREAKOUT_ROOM:
            self._update_state(BotState.IN_BREAKOUT)
        elif status == zoom.MEETING_STATUS_LEAVE_BREAKOUT_ROOM:
            self._update_state(BotState.IN_MEETING)
        elif status == zoom.MEETING_STATUS_ENDED:
            # Try to get more info about why meeting ended
            try:
                if self._meeting_service:
                    info = self._meeting_service.GetMeetingInfo()
                    if info:
                        print(f"[ZoomBot] Meeting info on end: {[m for m in dir(info) if not m.startswith('_')]}")
            except Exception as e:
                print(f"[ZoomBot] Could not get meeting info: {e}")
            self._update_state(BotState.IDLE)
            self.meeting_info = None
        elif status == zoom.MEETING_STATUS_FAILED:
            print(f"[ZoomBot] Meeting join FAILED with result: {result}")
            self._update_state(BotState.ERROR)
            self._join_result = False
            self._join_complete.set()
        elif status == zoom.MEETING_STATUS_DISCONNECTING:
            print(f"[ZoomBot] Meeting DISCONNECTING, result: {result}")
        elif status == zoom.MEETING_STATUS_WAITINGFORHOST:
            print("[ZoomBot] Waiting for host to start meeting...")
        elif status == zoom.MEETING_STATUS_IN_WAITING_ROOM:
            print("[ZoomBot] In waiting room - host needs to admit the bot")
        elif status == zoom.MEETING_STATUS_CONNECTING:
            print("[ZoomBot] Connecting to meeting...")

    def _on_audio_data(self, audio_bytes: bytes) -> None:
        try:
            self._audio_queue.put_nowait(audio_bytes)
        except:
            pass

    def _generate_jwt_token(self) -> str:
        import base64
        import hashlib
        import hmac

        header = {"alg": "HS256", "typ": "JWT"}
        iat = int(time.time())
        exp = iat + 86400

        payload = {
            "sdkKey": ZOOM_CLIENT_ID,
            "appKey": ZOOM_CLIENT_ID,
            "iat": iat,
            "exp": exp,
            "tokenExp": exp,
            "role": 0,
        }

        def b64_encode(data: dict) -> str:
            json_bytes = json.dumps(data, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(json_bytes).rstrip(b"=").decode()

        header_b64 = b64_encode(header)
        payload_b64 = b64_encode(payload)

        message = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            ZOOM_CLIENT_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

        return f"{header_b64}.{payload_b64}.{signature_b64}"

    def initialize_sdk(self) -> bool:
        if self.sdk_initialized:
            return True

        if not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
            print("[ZoomBot] Error: ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET required")
            self._update_state(BotState.ERROR)
            return False

        self._update_state(BotState.INITIALIZING)

        try:
            init_param = zoom.InitParam()
            init_param.strWebDomain = "https://zoom.us"
            init_param.enableLogByDefault = True

            result = zoom.InitSDK(init_param)
            if result != zoom.SDKERR_SUCCESS:
                print(f"[ZoomBot] SDK init failed: {result}")
                self._update_state(BotState.ERROR)
                return False

            print("[ZoomBot] SDK initialized")

            self._auth_service = zoom.CreateAuthService()
            self._auth_callback = AuthCallback(self._on_auth_result)
            self._auth_service.SetEvent(self._auth_callback)
            print("[ZoomBot] Auth service ready")

            auth_context = zoom.AuthContext()
            auth_context.jwt_token = self._generate_jwt_token()
            print("[ZoomBot] Calling SDKAuth...")

            result = self._auth_service.SDKAuth(auth_context)
            if result != zoom.SDKERR_SUCCESS:
                print(f"[ZoomBot] Auth call failed: {result}")
                self._update_state(BotState.ERROR)
                return False

            print("[ZoomBot] Auth initiated, waiting for callback...")
            self.sdk_initialized = True
            return True

        except Exception as e:
            print(f"[ZoomBot] SDK init error: {e}")
            import traceback
            traceback.print_exc()
            self._update_state(BotState.ERROR)
            return False

    def _setup_audio_capture(self) -> None:
        try:
            # First, join VOIP audio
            if self._meeting_service:
                audio_ctrl = self._meeting_service.GetMeetingAudioController()
                if audio_ctrl:
                    join_result = audio_ctrl.JoinVoip()
                    print(f"[ZoomBot] JoinVoip result: {join_result}")

            # Schedule raw recording start after VOIP connects
            def start_raw_recording() -> None:
                try:
                    if self._meeting_service:
                        rec_ctrl = self._meeting_service.GetMeetingRecordingController()
                        if rec_ctrl:
                            can_raw = rec_ctrl.CanStartRawRecording()
                            print(f"[ZoomBot] CanStartRawRecording: {can_raw}")

                            # Request recording privilege if supported
                            try:
                                if rec_ctrl.IsSupportRequestLocalRecordingPrivilege():
                                    print("[ZoomBot] Requesting local recording privilege...")
                                    req_result = rec_ctrl.RequestLocalRecordingPrivilege()
                                    print(f"[ZoomBot] RequestLocalRecordingPrivilege: {req_result}")
                            except Exception as e:
                                print(f"[ZoomBot] Recording privilege request: {e}")

                            # Try starting raw recording
                            raw_result = rec_ctrl.StartRawRecording()
                            print(f"[ZoomBot] StartRawRecording result: {raw_result}")

                    # Subscribe to raw audio
                    self._audio_helper = zoom.GetAudioRawdataHelper()
                    if self._audio_helper:
                        self._audio_callback = AudioCallback(self._on_audio_data)
                        result = self._audio_helper.subscribe(self._audio_callback, True)
                        print(f"[ZoomBot] Audio subscribe result: {result}")
                        if result == zoom.SDKERR_SUCCESS:
                            print("[ZoomBot] Audio streaming enabled!")
                except Exception as e:
                    print(f"[ZoomBot] Raw recording setup error: {e}")
                    import traceback
                    traceback.print_exc()

            from PyQt5.QtCore import QTimer
            QTimer.singleShot(2000, start_raw_recording)

        except Exception as e:
            print(f"[ZoomBot] Audio setup error: {e}")
            import traceback
            traceback.print_exc()

    @Slot(str, str, str)
    def _handle_join(self, meeting_number: str, password: str, display_name: str) -> None:
        print(f"[ZoomBot] Join request: {meeting_number}")
        self._join_result = None
        self._join_complete.clear()

        if self.state not in (BotState.AUTHENTICATED, BotState.IDLE):
            print(f"[ZoomBot] Cannot join: current state is {self.state.value}")
            self._join_result = False
            self._join_complete.set()
            return

        self._update_state(BotState.JOINING)

        try:
            join_param = zoom.JoinParam()
            join_param.userType = zoom.SDK_UT_WITHOUT_LOGIN

            # Use .param for JoinParam4WithoutLogin
            param = join_param.param
            param.meetingNumber = int(meeting_number.replace(" ", "").replace("-", ""))
            param.userName = display_name or BOT_DISPLAY_NAME
            param.psw = password
            param.isVideoOff = True
            param.isAudioOff = False

            self.meeting_info = MeetingInfo(
                meeting_number=meeting_number,
                password=password,
            )

            result = self._meeting_service.Join(join_param)
            if result != zoom.SDKERR_SUCCESS:
                print(f"[ZoomBot] Join failed: {result}")
                self._update_state(BotState.ERROR)
                self._join_result = False
                self._join_complete.set()
                return

            print("[ZoomBot] Join initiated, waiting for callback...")

        except Exception as e:
            print(f"[ZoomBot] Join error: {e}")
            import traceback
            traceback.print_exc()
            self._update_state(BotState.ERROR)
            self._join_result = False
            self._join_complete.set()

    @Slot()
    def _handle_leave(self) -> None:
        if self.state in (BotState.IDLE, BotState.LEAVING):
            return

        self._update_state(BotState.LEAVING)

        try:
            if self._meeting_service:
                self._meeting_service.Leave(zoom.LEAVE_MEETING)
        except Exception as e:
            print(f"[ZoomBot] Leave error: {e}")

        self.meeting_info = None
        self._update_state(BotState.IDLE)
        print("[ZoomBot] Left meeting")

    def join_meeting(self, meeting_number: str, password: str = "", display_name: str = "") -> bool:
        self.join_requested.emit(meeting_number, password, display_name)
        if self._join_complete.wait(timeout=60):
            return self._join_result or False
        else:
            print("[ZoomBot] Join timeout")
            return False

    def leave_meeting(self) -> None:
        self.leave_requested.emit()

    def get_status(self) -> dict:
        status = {
            "state": self.state.value,
            "sdk_initialized": self.sdk_initialized,
        }
        if self.meeting_info:
            status["meeting"] = {
                "meeting_number": self.meeting_info.meeting_number,
                "topic": self.meeting_info.topic,
                "joined_at": self.meeting_info.joined_at.isoformat() if self.meeting_info.joined_at else None,
                "breakout_room": self.meeting_info.breakout_room,
            }
        return status

    def cleanup(self) -> None:
        if self.state != BotState.IDLE:
            self._handle_leave()

        if self.sdk_initialized:
            try:
                if self._meeting_service:
                    zoom.DestroyMeetingService(self._meeting_service)
                if self._auth_service:
                    zoom.DestroyAuthService(self._auth_service)
                zoom.CleanUPSDK()
            except Exception:
                pass
            self.sdk_initialized = False

        print("[ZoomBot] Cleanup complete")


audio_queue: Queue = Queue(maxsize=1000)
bot_controller: ZoomBotController | None = None


async def audio_forwarder() -> None:
    while True:
        try:
            async with websockets.connect(TRANSCRIBER_WS_URL) as ws:
                print(f"[AudioForwarder] Connected to {TRANSCRIBER_WS_URL}")

                await ws.send(json.dumps({
                    "type": "bot_connected",
                    "bot_name": BOT_DISPLAY_NAME,
                }))

                while True:
                    try:
                        try:
                            audio_bytes = audio_queue.get_nowait()
                            await ws.send(audio_bytes)
                        except Empty:
                            await asyncio.sleep(0.1)
                            await ws.send(json.dumps({"type": "keepalive"}))
                    except Exception as e:
                        print(f"[AudioForwarder] Send error: {e}")
                        break

        except Exception as e:
            print(f"[AudioForwarder] Connection error: {e}")
            await asyncio.sleep(5)


async def command_server() -> None:
    async def handle_command(websocket: Any) -> None:
        global bot_controller
        async for message in websocket:
            try:
                cmd = json.loads(message)
                cmd_type = cmd.get("type", "")

                if cmd_type == "join":
                    meeting_number = cmd.get("meeting_number", "")
                    password = cmd.get("password", "")
                    display_name = cmd.get("display_name", BOT_DISPLAY_NAME)

                    if bot_controller:
                        success = bot_controller.join_meeting(meeting_number, password, display_name)
                        await websocket.send(json.dumps({
                            "type": "join_result",
                            "success": success,
                            "meeting_number": meeting_number,
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Bot not initialized",
                        }))

                elif cmd_type == "leave":
                    if bot_controller:
                        bot_controller.leave_meeting()
                    await websocket.send(json.dumps({
                        "type": "leave_result",
                        "success": True,
                    }))

                elif cmd_type == "status":
                    if bot_controller:
                        status = bot_controller.get_status()
                        await websocket.send(json.dumps({
                            "type": "status",
                            **status,
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "status",
                            "state": "not_initialized",
                        }))

                else:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": f"Unknown command: {cmd_type}",
                    }))

            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON",
                }))
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": str(e),
                }))

    async with websockets.serve(handle_command, "0.0.0.0", AUDIO_WS_PORT):
        print(f"[CommandServer] Listening on port {AUDIO_WS_PORT}")
        await asyncio.Future()


def run_asyncio_in_thread() -> None:
    async def run_tasks() -> None:
        await asyncio.gather(
            audio_forwarder(),
            command_server(),
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_tasks())


def main() -> None:
    global bot_controller

    print("[ZoomBot] Starting...")
    print(f"[ZoomBot] Display name: {BOT_DISPLAY_NAME}")
    print(f"[ZoomBot] Transcriber URL: {TRANSCRIBER_WS_URL}")
    print(f"[ZoomBot] Command port: {AUDIO_WS_PORT}")

    # Create Qt application
    app = QApplication(sys.argv)

    # Create bot controller
    bot_controller = ZoomBotController(audio_queue)

    def shutdown() -> None:
        print("\n[ZoomBot] Shutting down...")
        if bot_controller:
            bot_controller.cleanup()
        app.quit()

    signal.signal(signal.SIGINT, lambda s, f: shutdown())
    signal.signal(signal.SIGTERM, lambda s, f: shutdown())

    # Start asyncio tasks in a separate thread
    asyncio_thread = threading.Thread(target=run_asyncio_in_thread, daemon=True)
    asyncio_thread.start()

    # Use timer to delay SDK init until after event loop starts
    def delayed_init() -> None:
        print("[ZoomBot] Initializing SDK (delayed)...")
        if not bot_controller.initialize_sdk():
            print("[ZoomBot] SDK initialization failed")

    QTimer.singleShot(100, delayed_init)


    # Check auth result periodically (SDK callbacks don't fire reliably)
    def check_auth_result() -> None:
        if bot_controller._auth_service and bot_controller.state == BotState.INITIALIZING:
            try:
                result = bot_controller._auth_service.GetAuthResult()
                if result == zoom.AUTHRET_SUCCESS:
                    print("[AuthPoll] Auth succeeded!")
                    bot_controller._on_auth_result(result)
                elif result != zoom.AUTHRET_NONE:
                    print(f"[AuthPoll] Auth failed: {result}")
                    bot_controller._on_auth_result(result)
            except Exception as e:
                print(f"[AuthPoll] Error: {e}")

    auth_poll_timer = QTimer()
    auth_poll_timer.timeout.connect(check_auth_result)
    auth_poll_timer.start(500)  # Check every 500ms

    # Check meeting status periodically (in case meeting callbacks don't fire)
    last_status = [None]
    def check_meeting_status() -> None:
        if bot_controller._meeting_service and bot_controller.state == BotState.JOINING:
            try:
                status = bot_controller._meeting_service.GetMeetingStatus()
                if status != last_status[0]:
                    print(f"[MeetingPoll] Status: {status}")
                    last_status[0] = status
                    bot_controller._on_meeting_status(status, 0)
            except Exception:
                pass  # Service might not be ready yet

    meeting_poll_timer = QTimer()
    meeting_poll_timer.timeout.connect(check_meeting_status)
    meeting_poll_timer.start(500)  # Check every 500ms

    # Keep Qt event loop responsive
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(10)

    print("[ZoomBot] Qt event loop starting...")

    # Run Qt event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
