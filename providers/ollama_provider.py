"""Local Ollama provider adapter for NOVA."""

from __future__ import annotations

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

from nova_core.configuration import ProviderConfiguration

from .base import (
    ModelProvider,
    ProviderRequestError,
    ProviderResponse,
    ProviderUnavailableError,
)


DEFAULT_OLLAMA_SYSTEM_PROMPT = (
    "You are NOVA's private local AI specialist. "
    "Provide accurate, concise, and practical answers. "
    "Help with coding, summaries, planning, analysis, and offline tasks. "
    "Never request or expose passwords, API keys, tokens, credentials, "
    "or private secrets."
)


class OllamaProvider(ModelProvider):
    """Generate private and offline responses using local Ollama."""

    name = "ollama"
    is_local = True

    def __init__(
        self,
        configuration: ProviderConfiguration,
    ) -> None:
        if configuration.name.value != self.name:
            raise ValueError(
                "OllamaProvider requires an Ollama "
                "ProviderConfiguration."
            )

        super().__init__(
            model=configuration.model,
        )

        self.configuration = configuration
        self._client: AsyncOpenAI | None = None

    @property
    def configured(self) -> bool:
        """
        Return whether Ollama is enabled and has basic configuration.

        This does not guarantee that the Ollama server is currently
        running. Use health_check() to verify availability.
        """

        return (
            self.configuration.enabled
            and bool(self.model.strip())
            and bool(
                (
                    self.configuration.base_url
                    or ""
                ).strip()
            )
        )

    def _get_client(self) -> AsyncOpenAI:
        """Create or return the cached local Ollama client."""

        self.require_configured()

        if self._client is not None:
            return self._client

        base_url = (
            self.configuration.base_url
            or "http://localhost:11434/v1"
        )

        self._client = AsyncOpenAI(
            api_key="ollama",
            base_url=base_url,
            timeout=self.configuration.timeout_seconds,
        )

        return self._client

    async def health_check(self) -> bool:
        """
        Check whether Ollama is running and reachable.

        This does not generate a model response or spend cloud credits.
        """

        if not self.configured:
            return False

        try:
            client = self._get_client()

            await client.models.list()

            return True

        except (
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
        """Generate one standardized response using local Ollama."""

        cleaned_prompt = prompt.strip()

        if not cleaned_prompt:
            raise ProviderRequestError(
                "Ollama cannot generate a response "
                "for an empty prompt."
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
            else DEFAULT_OLLAMA_SYSTEM_PROMPT
        )

        try:
            request_client = client.with_options(
                timeout=effective_timeout,
            )

            response = (
                await request_client.chat.completions.create(
                    model=self.model,
                    temperature=0.2,
                    max_tokens=(
                        self.configuration.max_output_tokens
                    ),
                    messages=[
                        {
                            "role": "system",
                            "content": instructions,
                        },
                        {
                            "role": "user",
                            "content": cleaned_prompt,
                        },
                    ],
                )
            )

        except APITimeoutError as error:
            raise ProviderUnavailableError(
                "The local Ollama model took too long to respond."
            ) from error

        except APIConnectionError as error:
            raise ProviderUnavailableError(
                "Ollama is not running or NOVA could not "
                "connect to the local Ollama server."
            ) from error

        except APIStatusError as error:
            status_code = getattr(
                error,
                "status_code",
                None,
            )

            detail = (
                f" Status code: {status_code}."
                if status_code is not None
                else ""
            )

            raise ProviderRequestError(
                "Ollama rejected the generation request."
                f"{detail} Confirm that the configured model "
                f"'{self.model}' is installed."
            ) from error

        except Exception as error:
            raise ProviderRequestError(
                "Ollama could not complete the local "
                "generation request."
            ) from error

        if not response.choices:
            raise ProviderRequestError(
                "Ollama returned no response choices."
            )

        answer = response.choices[0].message.content

        if not isinstance(answer, str) or not answer.strip():
            raise ProviderRequestError(
                "Ollama returned an empty response."
            )

        metadata: dict[str, object] = {}

        usage = getattr(
            response,
            "usage",
            None,
        )

        if usage is not None:
            prompt_tokens = getattr(
                usage,
                "prompt_tokens",
                None,
            )

            completion_tokens = getattr(
                usage,
                "completion_tokens",
                None,
            )

            total_tokens = getattr(
                usage,
                "total_tokens",
                None,
            )

            if prompt_tokens is not None:
                metadata["input_tokens"] = (
                    prompt_tokens
                )

            if completion_tokens is not None:
                metadata["output_tokens"] = (
                    completion_tokens
                )

            if total_tokens is not None:
                metadata["total_tokens"] = (
                    total_tokens
                )

        return ProviderResponse(
            text=answer.strip(),
            provider=self.name,
            model=self.model,
            used_fallback=False,
            metadata=metadata,
        )