"use client";

import { useEffect, useRef } from "react";
import {
  CamIcon,
  CamOffIcon,
  EndIcon,
  MicIcon,
  MicOffIcon,
  SparkIcon,
  VolumeIcon,
  VolumeOffIcon,
} from "@/components/icons";

export type OrbState = "idle" | "connecting" | "listening" | "thinking" | "speaking";

export type ChatLine = { id: string; from: "user" | "nova"; text: string };

export type ToolEvent = { id: string; call: string; result?: string; running?: boolean };

const ORB_LABEL: Record<OrbState, string> = {
  idle: "Standing by",
  connecting: "Connecting…",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

export type ConsoleProps = {
  state: OrbState;
  statusPill: { text: string; tone: "ok" | "warn" | "info" | "off" };
  meta: string;
  transcript: ChatLine[];
  tools: ToolEvent[];
  micEnabled: boolean;
  camEnabled: boolean;
  speakerMuted: boolean;
  voice: string;
  room: string;
  onToggleMic: () => void;
  onToggleCam: () => void;
  onToggleSpeaker: () => void;
  onDisconnect: () => void;
  demoNote?: string;
};

export default function Console(props: ConsoleProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [props.transcript]);

  return (
    <div className="shell">
      {props.demoNote && <div className="demo-note">{props.demoNote}</div>}
      <div className="card">
        <header className="header">
          <div className="brand">
            <span className="logo">
              <SparkIcon size={17} />
            </span>
            NOVA
            <span className={`pill ${props.statusPill.tone}`}>{props.statusPill.text}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="meta">{props.meta}</span>
            <button onClick={props.onDisconnect}>Disconnect</button>
          </div>
        </header>

        <div className="grid">
          <div className="main-col">
            <div className="orb-wrap">
              <div className={`orb ${props.state}`}>
                <MicIcon size={34} />
              </div>
              <span className="orb-label">{ORB_LABEL[props.state]}</span>
            </div>

            <div className="transcript" ref={scrollRef}>
              {props.transcript.length === 0 ? (
                <span className="transcript-empty">
                  Say something — the conversation will appear here.
                </span>
              ) : (
                props.transcript.map((line) => (
                  <div key={line.id} className={`bubble ${line.from}`}>
                    {line.text}
                  </div>
                ))
              )}
            </div>

            <div className="controls">
              <button
                className={`ctl ${props.micEnabled ? "" : "off"}`}
                aria-label={props.micEnabled ? "Mute microphone" : "Unmute microphone"}
                title={props.micEnabled ? "Mute microphone" : "Unmute microphone"}
                onClick={props.onToggleMic}
              >
                {props.micEnabled ? <MicIcon /> : <MicOffIcon />}
              </button>
              <button
                className={`ctl ${props.camEnabled ? "" : "off"}`}
                aria-label={props.camEnabled ? "Turn camera off" : "Turn camera on"}
                title={props.camEnabled ? "Turn camera off" : "Turn camera on"}
                onClick={props.onToggleCam}
              >
                {props.camEnabled ? <CamIcon /> : <CamOffIcon />}
              </button>
              <button
                className={`ctl ${props.speakerMuted ? "off" : ""}`}
                aria-label={props.speakerMuted ? "Unmute NOVA" : "Mute NOVA"}
                title={props.speakerMuted ? "Unmute NOVA" : "Mute NOVA"}
                onClick={props.onToggleSpeaker}
              >
                {props.speakerMuted ? <VolumeOffIcon /> : <VolumeIcon />}
              </button>
              <button
                className="ctl danger"
                aria-label="End session"
                title="End session"
                onClick={props.onDisconnect}
              >
                <EndIcon />
              </button>
            </div>
          </div>

          <div className="side-col">
            <span className="panel-title">Tool activity</span>
            {props.tools.length === 0 ? (
              <div className="tools-empty">
                When NOVA uses a tool (weather, Spotify, files…), it shows up here.
              </div>
            ) : (
              props.tools.map((tool) => (
                <div key={tool.id} className={`tool-entry ${tool.running ? "running" : ""}`}>
                  <div className="tool-call">{tool.call}</div>
                  <div className="tool-result">{tool.running ? "Running…" : tool.result}</div>
                </div>
              ))
            )}

            <div className="session-info">
              <span className="panel-title">Session</span>
              <div className="kv">
                <span className="k">Mic</span>
                <span className={`v ${props.micEnabled ? "ok" : "off"}`}>
                  {props.micEnabled ? "Live" : "Muted"}
                </span>
              </div>
              <div className="kv">
                <span className="k">Camera</span>
                <span className={`v ${props.camEnabled ? "ok" : "off"}`}>
                  {props.camEnabled ? "On" : "Off"}
                </span>
              </div>
              <div className="kv">
                <span className="k">Voice</span>
                <span className="v">{props.voice}</span>
              </div>
              <div className="kv">
                <span className="k">Room</span>
                <span className="v" style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 12 }}>
                  {props.room}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
