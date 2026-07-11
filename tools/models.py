import os

from livekit.agents import RunContext, function_tool
from openai import AsyncOpenAI

from .common import logger


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

_groq_client: AsyncOpenAI | None = None


def get_groq_client() -> AsyncOpenAI | None:
    """Create or return the cached Groq client."""
    global _groq_client

    if _groq_client is not None:
        return _groq_client

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return None

    _groq_client = AsyncOpenAI(
        api_key=api_key,
        base_url=GROQ_BASE_URL,
    )

    return _groq_client


@function_tool()
async def ask_groq(
    context: RunContext,
    task: str,
) -> str:
    """Use Groq for fast coding, summarization, and text analysis."""
    client = get_groq_client()

    if client is None:
        return (
            "Groq is not configured. Add GROQ_API_KEY "
            "to the local environment file."
        )

    model = os.getenv(
        "GROQ_MODEL",
        DEFAULT_GROQ_MODEL,
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are NOVA's fast specialist model. "
                        "Give accurate, concise, practical answers. "
                        "Focus on coding, summaries, analysis, and "
                        "structured text tasks. Never request or reveal "
                        "API keys, passwords, tokens, or credentials."
                    ),
                },
                {
                    "role": "user",
                    "content": task,
                },
            ],
        )

        answer = response.choices[0].message.content

        if not answer:
            return "Groq returned an empty response."

        logger.info(
            "ask_groq completed with model=%s",
            model,
        )

        return answer

    except Exception:
        logger.exception("ask_groq failed")
        return (
            "Groq could not complete that task. "
            "The service may be unavailable or rate-limited."
        )