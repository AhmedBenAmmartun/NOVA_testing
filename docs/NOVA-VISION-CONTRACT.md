# NOVA Vision Contract

Status: Phase 0 contract. The live Vision client is not implemented by this patch.

## Purpose

NOVA is moving from screenshot-based vision to explicit live media sharing. The future NOVA Vision client will be the user-controlled owner of microphone and visual tracks. The agent receives only the media that client publishes into the active LiveKit room.

## VisualSource

Exactly one of these states describes the visual source:

- `NONE`
- `CAMERA`
- `WINDOW`
- `DISPLAY`
- `BROWSER_TAB`

## Session states

- `DISCONNECTED`
- `CONNECTING`
- `CONNECTED_NO_MEDIA`
- `MIC_ONLY`
- `VISUAL_ACTIVE`
- `SOURCE_SWITCHING`
- `STOPPING`

## Required invariants

1. At most one visual track may be active at a time.
2. Outside `VISUAL_ACTIVE`, no visual track may be available to NOVA.
3. Switching sources must unpublish and stop the old source before publishing the new source.
4. The exact outgoing visual track must be the track shown in the local preview.
5. No screenshots are created for normal vision.
6. No frame files are written to disk.
7. No visual history is retained by the Vision subsystem.
8. No background recording is allowed.
9. New window, display, or browser-tab access requires a trusted user gesture and OS/browser picker.
10. A voice command may stop current vision immediately.
11. A voice command may request that the trusted source picker open.
12. A voice command or model tool call may never authorize a new window, display, or browser tab by itself.
13. Closing the Vision window must unpublish active media and release camera/microphone handles.
14. A disconnected client must leave NOVA with no stale visual-access state.

## Active-source metadata

The trusted client/service may publish structured metadata containing only:

- source type
- human-readable source label
- LiveKit track SID
- LiveKit room/session ID
- participant identity
- active/inactive state
- started timestamp

Permission state must not be encoded as free-form text in the model prompt. User authorization belongs to the trusted UI / OS permission boundary.

## Preview requirement

The preview is a privacy boundary, not decoration. If the preview shows camera A, NOVA must receive camera A. If the preview shows one selected window, NOVA must receive only that selected window. Source changes must be reflected locally before or atomically with publication.

## Planned Phase 1 behavior

The first live client milestone is:

`Launch NOVA -> Vision client opens -> user explicitly enables camera and/or mic -> exact local preview -> LiveKit publish -> stop/close releases everything.`

Window, display, and browser-tab selection come after camera + mic is verified.


## Phase 1 implementation — 2026-08-13

The first trusted client is implemented under `vision-client/` as a small
Tauri 2 Windows surface using LiveKit's JavaScript client. The shell is
intentionally separate from the media/session contract so it can later be
replaced or embedded in Valo without changing the privacy model.

Phase 1 enables only `CAMERA` plus microphone audio:

- Connecting does **not** automatically enable camera or microphone.
- The user must explicitly toggle each device.
- The local camera preview attaches to the same `LocalVideoTrack` that is
  published as `Track.Source.Camera`.
- The short-lived participant token allows only `camera` and `microphone`
  publish sources.
- Closing the window disables camera/microphone, stops local media tracks,
  and disconnects the room before destroying the window.
- `WINDOW`, `DISPLAY`, and `BROWSER_TAB` remain disabled placeholders until
  Phase 2 adds trusted picker flows.
- Guardian's legacy `ImageGrab` path is retired; there is no screenshot
  fallback.
