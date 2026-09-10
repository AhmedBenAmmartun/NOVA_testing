"""OpenAI provider adapter for NOVA."""

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
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponse,
    ProviderUnavailableError,
)


DEFAULT_OPENAI_SYSTEM_PROMPT = (
    "You are NOVA's advanced reasoning specialist. "
    "Provide accurate, practical, and concise help with coding, "
    "debugging, planning, architecture, research, and multi-step "
    "analysis. Never request, reveal, store, or transform passwords, "
    "API keys, tokens, credential files, or other private secrets."
)


def _configured_environment_value(
    variable_name: str,
) -> str | None:
    """Return a real environment value while ignoring placeholders."""

    value = os.getenv(
        variable_name,
        "",
    ).strip()

    if not value:
        return None

    placeholders = {
        "replace_me",
        "your_key_here",
        "your-api-key",
        "your_api_key",
        "api-key-here",
    }

    if value.lower() in placeholders:
        return None

    return value


class OpenAIProvider(ModelProvider):
    """Generate specialist responses using OpenAI."""

    name = "openai"
    is_local = False

    def __init__(
        self,
        configuration: ProviderConfiguration,
    ) -> None:
        if configuration.name.value != self.name:
            raise ValueError(
                "OpenAIProvider requires an OpenAI "
                "ProviderConfiguration."
            )

        super().__init__(
            model=configuration.model,
        )

        self.configuration = configuration
        self._client: AsyncOpenAI | None = None

    @property
    def configured(self) -> bool:
        """Return whether OpenAI is enabled and has a usable API key."""

        if not self.configuration.enabled:
            return False

        variable_name = (
            self.configuration.api_key_environment_variable
            or "OPENAI_API_KEY"
        )

        return (
            bool(self.model.strip())
            and _configured_environment_value(
                variable_name
            )
            is not None
        )

    def _get_client(self) -> AsyncOpenAI:
        """Create or return the cached asynchronous OpenAI client."""

        self.require_configured()

        if self._client is not None:
            return self._client

        variable_name = (
            self.configuration.api_key_environment_variable
            or "OPENAI_API_KEY"
        )

        api_key = _configured_environment_value(
            variable_name
        )

        if api_key is None:
            raise ProviderNotConfiguredError(
                "OpenAI is not configured. Add OPENAI_API_KEY "
                "to the local environment file."
            )

        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=self.configuration.timeout_seconds,
        )

        return self._client

    async def health_check(self) -> bool:
        """
        Check whether OpenAI is configured and reachable.

        This does not generate an assistant response.
        """

        if not self.configured:
            return False

        try:
            client = self._get_client()

            await client.models.list()

            return True

        except (
            AuthenticationError,
            APIConnectionError,
            APITimeoutError,
            APIStatusError,
        ):
            return False

        except Exception:
            return False

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> ProviderResponse:
        """Generate one standardized NOVA provider response."""

        cleaned_prompt = prompt.strip()

        if not cleaned_prompt:
            raise ProviderRequestError(
                "OpenAI cannot generate a response for an empty prompt."
            )

        client = self._get_client()

        effective_timeout = (
            timeout_seconds
            if timeout_seconds > 0
            else self.configuration.timeout_seconds
        )

        instructions = (
            system_prompt.strip()
            if system_prompt
            and system_prompt.strip()
            else DEFAULT_OPENAI_SYSTEM_PROMPT
        )

        try:
            request_client = client.with_options(
                timeout=effective_timeout,
            )

            response = await request_client.responses.create(
                model=self.model,
                instructions=instructions,
                input=cleaned_prompt,
                max_output_tokens=(
                    self.configuration.max_output_tokens
                ),
            )

        except AuthenticationError as error:
            raise ProviderNotConfiguredError(
                "OpenAI authentication failed. Check OPENAI_API_KEY "
                "without sharing the key."
            ) from error

        except RateLimitError as error:
            raise ProviderRateLimitError(
                "OpenAI is currently rate-limited or the configured "
                "project has reached its available usage limit."
            ) from error

        except APITimeoutError as error:
            raise ProviderUnavailableError(
                "OpenAI took too long to respond."
            ) from error

        except APIConnectionError as error:
            raise ProviderUnavailableError(
                "NOVA could not connect to OpenAI."
            ) from error

        except APIStatusError as error:
            status_code = getattr(
                error,
                "status_code",
                None,
            )

            request_id = getattr(
                error,
                "request_id",
                None,
            )

            detail = (
                f" Status code: {status_code}."
                if status_code is not None
                else ""
            )

            request_detail = (
                f" Request ID: {request_id}."
                if request_id
                else ""
            )

            # Provider-level failures must reach the circuit breaker as
            # such; an ordinary 4xx rejection is this request's problem, not
            # OpenAI's availability.
            if status_code == 429:
                raise ProviderRateLimitError(
                    "OpenAI is currently rate-limited."
                    f"{detail}"
                    f"{request_detail}"
                ) from error

            if status_code == 408 or (
                isinstance(status_code, int)
                and status_code >= 500
            ):
                raise ProviderUnavailableError(
                    "OpenAI is temporarily unavailable."
                    f"{detail}"
                    f"{request_detail}"
                ) from error

            raise ProviderRequestError(
                "OpenAI rejected the request."
                f"{detail}"
                f"{request_detail}"
            ) from error

        except Exception as error:
            raise ProviderRequestError(
                "OpenAI could not complete the generation request."
            ) from error

        answer = getattr(
            response,
            "output_text",
            "",
        )

        if not isinstance(answer, str) or not answer.strip():
            raise ProviderRequestError(
                "OpenAI returned an empty response."
            )

        request_id = getattr(
            response,
            "_request_id",
            None,
        )

        metadata: dict[str, object] = {}

        if request_id:
            metadata["request_id"] = request_id

        usage = getattr(
            response,
            "usage",
            None,
        )

        if usage is not None:
            input_tokens = getattr(
                usage,
                "input_tokens",
                None,
            )

            output_tokens = getattr(
                usage,
                "output_tokens",
                None,
            )

            total_tokens = getattr(
                usage,
                "total_tokens",
                None,
            )

            if input_tokens is not None:
                metadata["input_tokens"] = input_tokens

            if output_tokens is not None:
                metadata["output_tokens"] = output_tokens

            if total_tokens is not None:
                metadata["total_tokens"] = total_tokens

        return ProviderResponse(
            text=answer.strip(),
            provider=self.name,
            model=self.model,
            used_fallback=False,
            metadata=metadata,
        )