# Third-Party Services And Licensing Notes

This file tracks the third-party services, SDKs, APIs, models, and packages used
by NOVA. It is not legal advice. Before making the repository public or
submitting to Devpost, verify current terms and licenses for the exact versions
used in the final project.

## Submission Rule To Satisfy

The Build Week project can use third-party SDKs, APIs, tools, models, and open
source libraries if NOVA is authorized to use them and follows the relevant
terms and licenses.

## Services And APIs

| Service | Used for | Required for demo? | Notes before submission |
| --- | --- | --- | --- |
| OpenAI Codex | Build workflow, implementation evidence, `/feedback` session | Yes | Keep Codex session logs and final `/feedback` session ID. |
| GPT-5.6 | Explicit reasoning and confirmed screen analysis | Yes | Used through OpenAI Responses API only when NOVA calls `ask_gpt56` or `analyze_screen_with_gpt56`. |
| LiveKit | Realtime agent/room infrastructure | Yes for voice/dev mode | LiveKit Cloud terms apply if using cloud services. |
| Google Gemini API | Current realtime voice model and text driver path | Yes for current voice path | Keep API key in `.env`; do not commit. |
| Groq API | Optional cloud specialist model tool | No | Keep API key in `.env`; describe as optional. |
| Ollama | Optional local specialist model tool and offline mode | No | Check individual model licenses for any model included or recommended. |
| Spotify API | Optional music playback | No | Requires user credentials and Spotify account capabilities. |
| DuckDuckGo Search | Web search tool | No | Used through Python package/API behavior; verify package terms. |
| Obsidian | Local vault searched by the `search_memory` tool (added 2026-07-15) | No (needs `OBSIDIAN_VAULT_PATH`) | Do not redistribute Obsidian; use only user-authorized vault access. All reads are local; nothing is uploaded. |

## Python Dependencies

Current dependencies from [requirements.txt](requirements.txt):

- `livekit-agents`
- `livekit-plugins-openai`
- `livekit-plugins-silero`
- `livekit-plugins-google`
- `livekit-plugins-noise-cancellation`
- `livekit-plugins-ai-coustics`
- `duckduckgo-search`
- `openai`
- `spotipy`
- `psutil`
- `requests`
- `python-dotenv`
- `pypdf`

Dashboard/frontend dependencies are not listed here because the dashboard
draft is parked locally and intentionally excluded from the current GitHub
snapshot.

Before submitting:

- [ ] Run a dependency license check or manually verify package licenses.
- [ ] Record any required notices for redistributed code.
- [ ] Verify frontend dependency licenses before making the repo public.
- [ ] Remove unused dependencies from `requirements.txt` if they are not used.
- [x] Confirmed 2026-07-16: `livekit-plugins-groq` was unused (no imports
      anywhere) — removed from `requirements.txt`.

## Model Notes

- Gemini Realtime is the current voice provider in `agent.py`.
- GPT-5.6 is the OpenAI reasoning and screen-analysis specialist.
- `ask_groq` defaults to Groq-hosted `llama-3.3-70b-versatile` unless
  overridden by `GROQ_MODEL`.
- `ask_ollama` defaults to local `mistral:latest` unless overridden by
  `OLLAMA_MODEL`.
- Locally installed Ollama models noted in project docs: `mistral`,
  `llama3.2`.

Before shipping or recommending a model:

- [ ] Verify the model license.
- [ ] Verify whether the model can be used in a hackathon/demo context.
- [ ] Do not bundle model weights unless their license permits redistribution.

## Assets And IP

Allowed:

- Original NOVA code written by Ahmed/Codex
- Original screenshots and demos that do not expose private data
- Original art/assets created for the project
- Open-source assets with compatible licenses and required attribution

Avoid unless permission is documented:

- Copyrighted characters
- Copyrighted music
- Third-party logos used as branding
- Private messages, private documents, or private account data
- API keys, tokens, secrets, or OAuth cache files

## Secret Handling

Never commit:

- `.env`
- `.env.local`
- `.spotify_cache`
- `credentials.json`
- `token.json`
- API keys, access tokens, refresh tokens, or private certificates

Use [.env.example](.env.example) for non-secret setup documentation.
