import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """
    Application configuration loaded from environment variables.

    No secret values are hard-coded into the source code.
    """

    llm_api_url: str
    llm_api_key: str
    llm_model: str

    request_timeout_seconds: float = 20.0
    llm_max_tokens: int = 2000

    @classmethod
    def from_environment(cls) -> "Settings":
        api_url = os.getenv("LLM_API_URL", "").strip()
        api_key = os.getenv("LLM_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", "").strip()


        timeout_raw = os.getenv(
            "LLM_TIMEOUT_SECONDS",
            "20"
        )

        max_tokens_raw = os.getenv(
            "LLM_MAX_TOKENS",
            "2000"
        )

        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise RuntimeError(
                "LLM_TIMEOUT_SECONDS must be numeric."
            ) from exc

        try:
            max_tokens = int(max_tokens_raw)
        except ValueError as exc:
            raise RuntimeError(
                "LLM_MAX_TOKENS must be an integer."
            ) from exc

        if timeout <= 0:
            raise RuntimeError(
                "LLM_TIMEOUT_SECONDS must be greater than zero."
            )

        if max_tokens <= 0:
            raise RuntimeError(
                "LLM_MAX_TOKENS must be greater than zero."
            )

        return cls(
            llm_api_url=api_url,
            llm_api_key=api_key,
            llm_model=model,
            request_timeout_seconds=timeout,
            llm_max_tokens=max_tokens,
        )


def get_settings() -> Settings:
    """
    Load settings for the current process.
    """
    return Settings.from_environment()