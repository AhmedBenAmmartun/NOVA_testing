# NOVA Provider Resilience P0

## Status

**LAB / NOT ACTIVE.**

This milestone starts from the verified A1 checkpoint
`f9e4f46c41c6a8f027f99f5f2efb53f2f0939ffa` in the isolated worktree
`C:\Projects\NOVA-Labs\nova-provider-resilience`.

## VERIFIED CURRENT before P0

NOVA already has a provider abstraction for normal text/specialist work:

- `nova_core.configuration` — provider/profile configuration.
- `nova_core.provider_registry` — OpenAI, Groq, and Ollama adapters.
- `nova_core.router.ModelRouter` — role selection, local-only routing,
  fallback attempts, and cloud-budget enforcement.
- `tools.specialist.ask_specialist` — the single public specialist tool.

The live LiveKit session was the exception: `agent.py` constructed
`google.realtime.RealtimeModel` directly and hard-coded the Gemini route/model
in learning metadata.

## P0 goal

Create one provider-neutral boundary for the **native realtime lane** without
rewriting NOVA or weakening verified vision behavior.

P0:

1. Keeps LiveKit.
2. Keeps Gemini native realtime audio/video as the supported realtime provider.
3. Moves Gemini model construction into `nova_core.realtime`.
4. Adds `NOVA_REALTIME_PROVIDER=gemini`.
5. Honors the existing `NOVA_REALTIME_MODEL`, `NOVA_VOICE`, and
   `NOVA_TEMPERATURE` configuration.
6. Makes learning metadata use the selected realtime route/model.
7. Fails closed if a text-only provider is selected as if it were native
   realtime.
8. Preserves `video_input=True`, all-video turn coverage, interruption
   behavior, capability tools, permissions, task runtime, and vision status
   transport.
9. Does not add a dependency or a second provider registry.

## What P0 does NOT claim

P0 does **not** provide transparent voice failover from Gemini Live to Groq,
OpenAI, or Ollama. Those existing providers are text-generation adapters.

A real non-Gemini voice fallback requires a separate pipeline:

`LiveKit audio -> STT -> existing ModelRouter -> TTS`

and an explicit vision strategy. That belongs to a later Provider Resilience
milestone after P0 is verified.

## Planned next milestone

Provider Resilience P1 should evaluate:

- provider health state and cooldowns/circuit breaking;
- startup/session-level fallback policy;
- STT -> ModelRouter -> TTS voice fallback;
- Groq/OpenAI/Ollama/OpenRouter through the text lane;
- preserving Gemini as the native live-vision specialist;
- latency and interruption benchmarks before any activation.

P1 must reuse the existing provider registry/router rather than create a
parallel routing system.
