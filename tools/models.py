import base64
import os
from pathlib import Path

from livekit.agents import RunContext, function_tool
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from .common import logger


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_OLLAMA_MODEL = "mistral:latest"

DEFAULT_OPENAI_MODEL = "gpt-5.6"
OPENAI_SYSTEM_PROMPT = (
    "You are NOVA's GPT-5.6 reasoning specialist. "
    "Help Ahmed with careful planning, screen understanding, "
    "debugging, and multi-step analysis. Be concise and practical. "
    "Do not request, reveal, transform, or retain passwords, API "
    "keys, tokens, credential files, or private secrets."
)

_groq_client: AsyncOpenAI | None = None
_ollama_client: AsyncOpenAI | None = None
_openai_client: AsyncOpenAI | None = None


class ModelUnavailableError(RuntimeError):
    """Raised when a configured NOVA model is unavailable."""


def _configured_env_value(name: str) -> str | None:
    """Return a real env value while ignoring common placeholders."""
    value = os.getenv(name, "").strip()

    if not value:
        return None

    if value.lower() in {
        "replace_me",
        "your_key_here",
        "your-api-key",
    }:
        return None

    return value


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
        timeout=30.0,
    )

    return _groq_client


def get_ollama_client() -> AsyncOpenAI:
    """Create or return the cached Ollama client."""
    global _ollama_client

    if _ollama_client is None:
        _ollama_client = AsyncOpenAI(
            api_key="ollama",
            base_url=os.getenv(
                "OLLAMA_BASE_URL",
                OLLAMA_BASE_URL,
            ),
            timeout=float(
                os.getenv(
                    "OLLAMA_TIMEOUT_SECONDS",
                    "120",
                )
            ),
        )

    return _ollama_client


def get_openai_client() -> AsyncOpenAI | None:
    """Create or return the cached OpenAI client."""
    global _openai_client

    if _openai_client is not None:
        return _openai_client

    api_key = _configured_env_value("OPENAI_API_KEY")

    if api_key is None:
        return None

    _openai_client = AsyncOpenAI(
        api_key=api_key,
        timeout=float(
            os.getenv(
                "OPENAI_TIMEOUT_SECONDS",
                "60",
            )
        ),
    )

    return _openai_client


def _openai_model() -> str:
    """Return the configured GPT-5.6 model name."""
    return (
        os.getenv(
            "OPENAI_MODEL",
            DEFAULT_OPENAI_MODEL,
        ).strip()
        or DEFAULT_OPENAI_MODEL
    )


def _openai_max_output_tokens() -> int:
    """Return the max output budget for OpenAI responses."""
    return int(
        os.getenv(
            "OPENAI_MAX_OUTPUT_TOKENS",
            "800",
        )
    )


def _extract_response_text(response: object) -> str:
    """Extract text from a Responses API result."""
    output_text = getattr(response, "output_text", "")

    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    return ""


async def run_groq(task: str) -> str:
    """Run a task through NOVA's Groq specialist."""
    client = get_groq_client()

    if client is None:
        raise ModelUnavailableError(
            "Groq is not configured. Add GROQ_API_KEY "
            "to the local environment file."
        )

    model = os.getenv(
        "GROQ_MODEL",
        DEFAULT_GROQ_MODEL,
    )

    response = await client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=int(
            os.getenv(
                "GROQ_MAX_TOKENS",
                "600",
            )
        ),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are NOVA's fast specialist model. "
                    "Give accurate, concise, practical answers. "
                    "Focus on coding, summaries, analysis, "
                    "research, and structured text tasks. "
                    "Never request or reveal passwords, API "
                    "keys, tokens, or credentials."
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
        raise RuntimeError(
            "Groq returned an empty response."
        )

    logger.info(
        "run_groq completed with model=%s",
        model,
    )

    return answer.strip()


async def run_ollama(task: str) -> str:
    """Run a private or offline task through local Ollama."""
    client = get_ollama_client()

    model = os.getenv(
        "OLLAMA_MODEL",
        DEFAULT_OLLAMA_MODEL,
    )

    response = await client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=int(
            os.getenv(
                "OLLAMA_MAX_TOKENS",
                "400",
            )
        ),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are NOVA's private local specialist. "
                    "Give accurate, concise, practical answers. "
                    "Focus on coding, summaries, analysis, "
                    "research, and structured text tasks. "
                    "Never request or reveal passwords, API "
                    "keys, tokens, or credentials."
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
        raise RuntimeError(
            "Ollama returned an empty response."
        )

    logger.info(
        "run_ollama completed with model=%s",
        model,
    )

    return answer.strip()


async def run_gpt56(task: str) -> str:
    """Run a task through NOVA's GPT-5.6 specialist."""
    client = get_openai_client()

    if client is None:
        raise ModelUnavailableError(
            "GPT-5.6 is not configured. Add OPENAI_API_KEY "
            "to the local environment file."
        )

    model = _openai_model()

    response = await client.responses.create(
        model=model,
        instructions=OPENAI_SYSTEM_PROMPT,
        input=task,
        max_output_tokens=_openai_max_output_tokens(),
    )

    answer = _extract_response_text(response)

    if not answer:
        raise RuntimeError(
            "GPT-5.6 returned an empty response."
        )

    logger.info(
        "run_gpt56 completed with model=%s",
        model,
    )

    return answer


async def run_gpt56_with_image(
    image_path: Path,
    question: str,
) -> str:
    """Ask GPT-5.6 to analyze a local image."""
    client = get_openai_client()

    if client is None:
        raise ModelUnavailableError(
            "GPT-5.6 is not configured. Add OPENAI_API_KEY "
            "to the local environment file."
        )

    if not image_path.is_file():
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    image_bytes = image_path.read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode(
        "ascii"
    )

    model = _openai_model()

    response = await client.responses.create(
        model=model,
        instructions=OPENAI_SYSTEM_PROMPT,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": question,
                    },
                    {
                        "type": "input_image",
                        "image_url": (
                            "data:image/png;base64,"
                            f"{image_b64}"
                        ),
                        "detail": "auto",
                    },
                ],
            }
        ],
        max_output_tokens=_openai_max_output_tokens(),
    )

    answer = _extract_response_text(response)

    if not answer:
        raise RuntimeError(
            "GPT-5.6 returned an empty screen analysis."
        )

    logger.info(
        "run_gpt56_with_image completed with model=%s path=%s",
        model,
        image_path,
    )

    return answer


@function_tool()
async def ask_groq(
    context: RunContext,
    task: str,
) -> str:
    """Use Groq for fast coding, research, and analysis."""
    try:
        return await run_groq(task)

    except ModelUnavailableError as error:
        return str(error)

    except Exception:
        logger.exception("ask_groq failed")
        return (
            "Groq could not complete that task. "
            "The service may be unavailable or rate-limited."
        )


@function_tool()
async def ask_ollama(
    context: RunContext,
    task: str,
) -> str:
    """Use local Ollama for private or offline tasks."""
    try:
        return await run_ollama(task)

    except APIConnectionError:
        logger.exception(
            "ask_ollama: server unreachable"
        )
        return (
            "Ollama is not running on this computer. "
            "Start Ollama and try again."
        )

    except Exception:
        logger.exception("ask_ollama failed")
        return (
            "Ollama could not complete that task. "
            "Confirm that the selected model is installed."
        )


@function_tool()
async def ask_gpt56(
    context: RunContext,
    task: str,
) -> str:
    """Use GPT-5.6 for substantial reasoning, planning, and analysis."""
    try:
        return await run_gpt56(task)

    except ModelUnavailableError as error:
        return str(error)

    except AuthenticationError:
        logger.exception("ask_gpt56: authentication failed")
        return (
            "GPT-5.6 authentication failed. Check the local "
            "OPENAI_API_KEY without sharing it."
        )

    except RateLimitError:
        logger.exception("ask_gpt56: rate limited")
        return (
            "GPT-5.6 is rate-limited or out of available credits. "
            "Try again later or check the OpenAI project budget."
        )

    except APITimeoutError:
        logger.exception("ask_gpt56: request timed out")
        return (
            "GPT-5.6 took too long to respond. Try a smaller "
            "request."
        )

    except APIConnectionError:
        logger.exception("ask_gpt56: connection failed")
        return (
            "NOVA could not reach OpenAI. Check the network "
            "connection and try again."
        )

    except APIStatusError:
        logger.exception("ask_gpt56: API status error")
        return (
            "OpenAI rejected the GPT-5.6 request. Check the "
            "configured model name and project access."
        )

    except Exception:
        logger.exception("ask_gpt56 failed")
        return (
            "GPT-5.6 could not complete that task."
        )
