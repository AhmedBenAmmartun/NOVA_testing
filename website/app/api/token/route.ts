import { AccessToken } from "livekit-server-sdk";
import { RoomAgentDispatch, RoomConfiguration } from "@livekit/protocol";
import { loadAgentEnv } from "@/lib/env";

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const env = loadAgentEnv();

  const expected = env.NOVA_SITE_PASSCODE;
  if (!expected) {
    return Response.json(
      { error: "NOVA_SITE_PASSCODE is not set in the agent .env file." },
      { status: 500 },
    );
  }
  if (body.passcode !== expected) {
    return Response.json({ error: "Wrong passcode." }, { status: 401 });
  }

  const url = env.LIVEKIT_URL;
  const apiKey = env.LIVEKIT_API_KEY;
  const apiSecret = env.LIVEKIT_API_SECRET;
  if (!url || !apiKey || !apiSecret) {
    return Response.json(
      { error: "LiveKit credentials are missing from the agent .env file." },
      { status: 500 },
    );
  }

  const room = `nova-web-${Math.random().toString(36).slice(2, 8)}`;
  const token = new AccessToken(apiKey, apiSecret, {
    identity: "ahmed-web",
    ttl: "2h",
  });
  token.addGrant({
    roomJoin: true,
    room,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true,
  });
  // Explicitly dispatch the NOVA agent worker into this room.
  token.roomConfig = new RoomConfiguration({
    agents: [new RoomAgentDispatch({ agentName: "my-agent" })],
  });

  return Response.json({ url, room, token: await token.toJwt() });
}
