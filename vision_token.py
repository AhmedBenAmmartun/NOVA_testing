"""Generate short-lived LiveKit credentials for the local NOVA Vision client.

This helper is invoked only by the trusted Tauri backend. It reads the local
NOVA environment files, creates a unique room, restricts publishing to camera
and microphone for Phase 1, and dispatches the named NOVA agent. It never
prints API keys or secrets.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants


PROJECT_ROOT = Path(__file__).resolve().parent
AGENT_NAME = "my-agent"
TOKEN_TTL = dt.timedelta(minutes=15)


def _load_local_environment() -> None:
    load_dotenv(PROJECT_ROOT / ".env.local", override=False)
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def _new_session_names() -> tuple[str, str]:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    nonce = secrets.token_hex(6)
    return f"nova-vision-{stamp}-{nonce}", f"nova-user-{nonce}"


def create_connection_credentials() -> dict[str, str]:
    _load_local_environment()

    server_url = (os.getenv("LIVEKIT_URL") or "").strip()
    if not server_url.startswith(("ws://", "wss://")):
        raise RuntimeError("LIVEKIT_URL is missing or invalid")

    # AccessToken reads LIVEKIT_API_KEY/LIVEKIT_API_SECRET from the environment.
    # We intentionally never copy either secret into the frontend or output JSON.
    room_name, identity = _new_session_names()
    grants = VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
        can_publish_sources=["camera", "microphone"],
        can_update_own_metadata=False,
    )

    token = (
        AccessToken()
        .with_identity(identity)
        .with_name("NOVA Vision User")
        .with_ttl(TOKEN_TTL)
        .with_grants(grants)
        .with_room_config(
            RoomConfiguration(
                agents=[
                    RoomAgentDispatch(
                        agent_name=AGENT_NAME,
                        metadata='{"client":"nova-vision","phase":1}',
                    )
                ]
            )
        )
        .to_jwt()
    )

    return {
        "serverUrl": server_url,
        "participantToken": token,
        "roomName": room_name,
        "identity": identity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--json", action="store_true", help="Emit connection JSON.")
    args = parser.parse_args()

    if not args.json:
        parser.error("--json is required")

    try:
        credentials = create_connection_credentials()
    except Exception as error:
        print(
            f"NOVA Vision credential generation failed ({type(error).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(credentials, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
