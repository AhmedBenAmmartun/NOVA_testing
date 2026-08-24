"""Groq provider adapter for NOVA using Groq's OpenAI-compatible API."""

from __future__ import annotations

import os

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from nova_core.configuration import ProviderConfiguration

from .base import (
    ModelProvider,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderResponse,
    ProviderUnavailableError,
)


DEFAULT_GROQ_SYSTEM_PROMPT = (
    "You are NOVA's fast specialist. Give accurate, concise, grounded answers. "
    "For classroom questions, preserve technical terminology and explicitly "
    "account for likely speech-to-text errors when course context supports a "
    "clear correction. Never invent professor statements, deadlines, policies, "
    "or source evidence."
)

# Groq shut these models down for free/developer-tier usage in August 2026.
_DEPRECATED_MODEL_REPLACEMENTS = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
}


def _configured_environment_value(variable_name: str) -> str | None:
    value = os.getenv(variable_name, "").strip()
    if not value:
        return None
    placeholders = {
        "replace_me",
        "your_key_here",
        "your-api-key",
        "your_api_key",
        "api-key-here",
    }
    return None if value.lower() in placeholders else value


class GroqProvider(ModelProvider):
    """Generate fast specialist responses through GroqCloud."""

    name = "groq"
    is_local = False

    def __init__(self, configuration: ProviderConfiguration) -> None:
        if configuration.name.value != self.name:
            raise ValueError("GroqProvider requires a Groq ProviderConfiguration.")

        effective_model = _DEPRECATED_MODEL_REPLACEMENTS.get(
            configuration.model.strip(),
            configuration.model.strip(),
        )
        super().__init__(model=effective_model)
        self.configuration = configuration
        self.configured_model = configuration.model.strip()
        self.model_was_migrated = effective_model != self.configured_model
        self._client: AsyncOpenAI | None = None

    @property
    def configured(self) -> bool:
        if not self.configuration.enabled:
            return False
        variable_name = (
            self.configuration.api_key_environment_variable or "GROQ_API_KEY"
        )
        return bool(self.model.strip()) and _configured_environment_value(variable_name) is not None

    def _get_client(self) -> AsyncOpenAI:
        self.require_configured()
        if self._client is not None:
            return self._client

        variable_name = (
            self.configuration.api_key_environment_variable or "GROQ_API_KEY"
        )
        api_key = _configured_environment_value(variable_name)
        if api_key is None:
            raise ProviderNotConfiguredError(
                "Groq is not configured. Add GROQ_API_KEY to the local environment file."
            )

        base_url = (self.configuration.base_url or "https://api.groq.com/openai/v1").rstrip("/")
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.configuration.timeout_seconds,
        )
        return self._client

    async def health_check(self) -> bool:
        if not self.configured:
            return False
        try:
            await self._get_client().models.list()
            return True
        except Exception:
            return False

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> ProviderResponse:
        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            raise ProviderRequestError("Groq cannot generate a response for an empty prompt.")

        effective_timeout = (
            timeout_seconds if timeout_seconds > 0 else self.configuration.timeout_seconds
        )
        instructions = (
            system_prompt.strip()
            if system_prompt and system_prompt.strip()
            else DEFAULT_GROQ_SYSTEM_PROMPT
        )

        try:
            client = self._get_client().with_options(timeout=effective_timeout)
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": cleaned_prompt},
                ],
                max_tokens=self.configuration.max_output_tokens,
                temperature=0.2,
            )
        except AuthenticationError as error:
            raise ProviderNotConfiguredError(
                "Groq authentication failed. Check GROQ_API_KEY without sharing the key."
            ) from error
        except RateLimitError as error:
            raise ProviderUnavailableError(
                "Groq is currently rate-limited or the account reached its available usage limit."
            ) from error
        except APITimeoutError as error:
            raise ProviderUnavailableError("Groq took too long to respond.") from error
        except APIConnectionError as error:
            raise ProviderUnavailableError("NOVA could not connect to Groq.") from error
        except APIStatusError as error:
            status_code = getattr(error, "status_code", None)
            detail = f" Status code: {status_code}." if status_code is not None else ""
            raise ProviderRequestError(f"Groq rejected the request.{detail}") from error
        except Exception as error:
            raise ProviderRequestError("Groq could not complete the generation request.") from error

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise ProviderRequestError("Groq returned no completion choices.")
        message = getattr(choices[0], "message", None)
        answer = getattr(message, "content", "") if message is not None else ""
        if not isinstance(answer, str) or not answer.strip():
            raise ProviderRequestError("Groq returned an empty response.")

        metadata: dict[str, object] = {
            "configured_model": self.configured_model,
            "model_migrated": self.model_was_migrated,
        }
        usage = getattr(response, "usage", None)
        if usage is not None:
            for source_name, target_name in (
                ("prompt_tokens", "input_tokens"),
                ("completion_tokens", "output_tokens"),
                ("total_tokens", "total_tokens"),
            ):
                value = getattr(usage, source_name, None)
                if value is not None:
                    metadata[target_name] = value

        return ProviderResponse(
            text=answer.strip(),
            provider=self.name,
            model=self.model,
            used_fallback=False,
            metadata=metadata,
        )
