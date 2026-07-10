"use client";

import { useCallback, useMemo, useState } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useConnectionState,
  useDataChannel,
  useLocalParticipant,
  useRoomContext,
  useTranscriptions,
  useVoiceAssistant,
} from "@livekit/components-react";
import { ConnectionState } from "livekit-client";
import Console, { type ChatLine, type OrbState, type ToolEvent } from "@/components/Console";
import { SparkIcon } from "@/components/icons";

type Credentials = { url: string; token: string; room: string };

export default function NovaApp({ demo }: { demo: boolean }) {
  const [creds, setCreds] = useState<Credentials | null>(null);

  if (demo) return <DemoConsole />;
  if (!creds) return <Gate onConnected={setCreds} />;
  return (
    <LiveKitRoom
      serverUrl={creds.url}
      token={creds.token}
      connect
      audio
      video={false}
      onDisconnected={() => setCreds(null)}
    >
      <RoomAudioRenderer />
      <LiveConsole room={creds.room} />
    </LiveKitRoom>
  );
}

function Gate({ onConnected }: { onConnected: (creds: Credentials) => void }) {
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const connect = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passcode }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Connection failed.");
      onConnected(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed.");
      setBusy(false);
    }
  }, [passcode, onConnected]);

  return (
    <div className="gate">
      <div className="gate-card">
        <span className="gate-logo">
          <SparkIcon size={30} />
        </span>
        <h1>NOVA</h1>
        <p className="gate-sub">Ahmed&apos;s personal AI operating assistant</p>
        <div className="gate-actions">
          <input
            type="password"
            placeholder="Access code"
            value={passcode}
            onChange={(e) => setPasscode(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && passcode && !busy && connect()}
            aria-label="Access code"
          />
          <button className="gate-primary" onClick={connect} disabled={!passcode || busy}>
            {busy ? "Connecting…" : "Connect"}
          </button>
        </div>
        <p className="gate-error">{error}</p>
      </div>
    </div>
  );
}

function LiveConsole({ room }: { room: string }) {
  const roomCtx = useRoomContext();
  const connectionState = useConnectionState();
  const { state: agentState } = useVoiceAssistant();
  const { localParticipant, isMicrophoneEnabled, isCameraEnabled } = useLocalParticipant();
  const transcriptions = useTranscriptions();
  const [tools, setTools] = useState<ToolEvent[]>([]);
  const [speakerMuted, setSpeakerMuted] = useState(false);

  useDataChannel("nova.tools", (msg) => {
    try {
      const data = JSON.parse(new TextDecoder().decode(msg.payload));
      setTools((prev) => {
        const next = prev.filter((t) => t.id !== data.id);
        next.push({
          id: String(data.id ?? Date.now()),
          call: String(data.call ?? "tool"),
          result: data.result ? String(data.result) : undefined,
          running: !data.result,
        });
        return next.slice(-8);
      });
    } catch {
      // ignore malformed tool events
    }
  });

  const orbState: OrbState = useMemo(() => {
    if (connectionState !== ConnectionState.Connected) return "connecting";
    switch (agentState) {
      case "listening":
        return "listening";
      case "thinking":
        return "thinking";
      case "speaking":
        return "speaking";
      case "connecting":
      case "initializing":
        return "connecting";
      default:
        return "idle";
    }
  }, [connectionState, agentState]);

  const statusPill = useMemo(() => {
    if (connectionState === ConnectionState.Connected)
      return { text: "Connected", tone: "ok" as const };
    if (connectionState === ConnectionState.Reconnecting)
      return { text: "Reconnecting…", tone: "warn" as const };
    return { text: "Connecting…", tone: "warn" as const };
  }, [connectionState]);

  const transcript: ChatLine[] = useMemo(
    () =>
      transcriptions.map((seg, i) => ({
        id: seg.streamInfo?.id ?? `seg-${i}`,
        from:
          seg.participantInfo?.identity === localParticipant.identity ? "user" : "nova",
        text: seg.text,
      })),
    [transcriptions, localParticipant.identity],
  );

  const toggleSpeaker = useCallback(() => {
    const muted = !speakerMuted;
    setSpeakerMuted(muted);
    roomCtx.remoteParticipants.forEach((p) => p.setVolume(muted ? 0 : 1));
  }, [speakerMuted, roomCtx]);

  return (
    <Console
      state={orbState}
      statusPill={statusPill}
      meta="Agent: my-agent · LiveKit Cloud"
      transcript={transcript}
      tools={tools}
      micEnabled={isMicrophoneEnabled}
      camEnabled={isCameraEnabled}
      speakerMuted={speakerMuted}
      voice="Achird"
      room={room}
      onToggleMic={() => localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled)}
      onToggleCam={() => localParticipant.setCameraEnabled(!isCameraEnabled)}
      onToggleSpeaker={toggleSpeaker}
      onDisconnect={() => roomCtx.disconnect()}
    />
  );
}

function DemoConsole() {
  const [micEnabled, setMicEnabled] = useState(true);
  const [camEnabled, setCamEnabled] = useState(false);
  const [speakerMuted, setSpeakerMuted] = useState(false);

  const transcript: ChatLine[] = [
    { id: "1", from: "user", text: "Nova, what's the weather in Tunis?" },
    { id: "2", from: "nova", text: "It's sunny and 83 degrees in Tunis right now." },
    { id: "3", from: "user", text: "Nice. Play some music." },
    { id: "4", from: "nova", text: "Resuming Spotify for you." },
  ];
  const tools: ToolEvent[] = [
    { id: "1", call: 'get_weather("Tunis")', result: "Tunis: sunny, +83°F" },
    { id: "2", call: 'control_music("play_pause")', result: "Sent play/pause to the player" },
    { id: "3", call: "get_current_song()", running: true },
  ];

  return (
    <Console
      state="listening"
      statusPill={{ text: "Demo", tone: "info" }}
      meta="Sample data — not connected"
      transcript={transcript}
      tools={tools}
      micEnabled={micEnabled}
      camEnabled={camEnabled}
      speakerMuted={speakerMuted}
      voice="Achird"
      room="nova-web-demo"
      onToggleMic={() => setMicEnabled((v) => !v)}
      onToggleCam={() => setCamEnabled((v) => !v)}
      onToggleSpeaker={() => setSpeakerMuted((v) => !v)}
      onDisconnect={() => (window.location.href = "/")}
      demoNote="Demo view — this is sample data. Open the home page and enter your access code for a live session."
    />
  );
}
