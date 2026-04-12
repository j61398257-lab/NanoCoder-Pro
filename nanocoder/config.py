"""Configuration - env vars and defaults."""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env from the project root (two levels up from this file)."""
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


@dataclass
class GatewayModelConfig:
    """Configuration for a single model in the gateway."""
    name: str = ""
    api_key: str = ""
    base_url: str | None = None
    tier: str = "default"
    max_tokens: int = 4096
    temperature: float = 0.0


@dataclass
class Config:
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    max_context_tokens: int = 128_000
    gateway_models: list[GatewayModelConfig] | None = None

    @classmethod
    def from_env(cls) -> "Config":
        api_key = (
            os.getenv("NANOCODER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or ""
        )

        gateway_models = cls._parse_gateway_env()

        return cls(
            model=os.getenv("NANOCODER_MODEL", "gpt-4o"),
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("NANOCODER_BASE_URL"),
            max_tokens=int(os.getenv("NANOCODER_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("NANOCODER_TEMPERATURE", "0")),
            max_context_tokens=int(os.getenv("NANOCODER_MAX_CONTEXT", "128000")),
            gateway_models=gateway_models or None,
        )

    @staticmethod
    def _parse_gateway_env() -> list[GatewayModelConfig]:
        """Parse NANOCODER_GATEWAY_MODELS env var.

        Format: 'model1:tier:base_url:api_key,model2:tier:base_url:api_key'
        Example: 'gpt-4o-mini:fast::sk-abc,gpt-4o:strong::sk-abc'
        Empty base_url fields inherit from OPENAI_BASE_URL.
        """
        raw = os.getenv("NANOCODER_GATEWAY_MODELS", "")
        if not raw:
            return []
        models: list[GatewayModelConfig] = []
        default_base = os.getenv("OPENAI_BASE_URL") or os.getenv("NANOCODER_BASE_URL")
        default_key = (
            os.getenv("NANOCODER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        for part in raw.split(","):
            fields = part.strip().split(":")
            if len(fields) < 1 or not fields[0]:
                continue
            name = fields[0].strip()
            tier = fields[1].strip() if len(fields) > 1 and fields[1].strip() else "default"
            base_url = fields[2].strip() if len(fields) > 2 and fields[2].strip() else default_base
            api_key = fields[3].strip() if len(fields) > 3 and fields[3].strip() else default_key
            models.append(GatewayModelConfig(
                name=name, api_key=api_key, base_url=base_url, tier=tier,
            ))
        return models
