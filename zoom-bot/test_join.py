#!/usr/bin/env python3
"""Test script to send join command to the Zoom bot."""

import asyncio
import json
import sys

import websockets


async def main(meeting_number: str, password: str = ""):
    """Send join command to the Zoom bot."""
    uri = "ws://localhost:3001"

    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as ws:
        # Get initial status
        await ws.send(json.dumps({"type": "status"}))
        response = await ws.recv()
        status = json.loads(response)
        print(f"Bot status: {status}")

        if status.get("state") != "authenticated":
            print(f"Bot not ready, state is: {status.get('state')}")
            return

        # Send join command
        print(f"\nJoining meeting {meeting_number}...")
        await ws.send(json.dumps({
            "type": "join",
            "meeting_number": meeting_number,
            "password": password,
        }))

        # Wait for response (with timeout)
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=120)
            result = json.loads(response)
            print(f"Join result: {result}")
        except asyncio.TimeoutError:
            print("Timeout waiting for join response")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_join.py <meeting_number> [password]")
        print("Example: python test_join.py 1234567890 mypassword")
        sys.exit(1)

    meeting = sys.argv[1]
    pwd = sys.argv[2] if len(sys.argv) > 2 else ""

    asyncio.run(main(meeting, pwd))
