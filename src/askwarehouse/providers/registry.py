"""Picks a Provider based on what's available.

Deployment default is a free-tier hosted model (Gemini, then Groq) since the
Vercel runtime has no GPU for the local Qwen model. Order of precedence:

  1. an explicit name passed in (or ASKWAREHOUSE_PROVIDER env var)
  2. whichever provider key is present in the environment
  3. 'local' (the on-GPU Qwen model) as the last resort

``get_provider(name, api_key=...)`` with an explicit key is never cached, so
a request that brings its own key can't leak it into another request's
provider instance.
"""
import os
from dotenv import load_dotenv

from askwarehouse.providers.base import Provider

load_dotenv()

_cached: dict[str, Provider] = {}

# provider name -> default model (overridable via ASKWAREHOUSE_MODEL)
DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4.1",
}

_ENV_KEYS = [
    ("gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    ("groq", ("GROQ_API_KEY",)),
    ("anthropic", ("ANTHROPIC_API_KEY",)),
    ("openai", ("OPENAI_API_KEY",)),
]


def _auto_choice() -> str:
    for name, keys in _ENV_KEYS:
        if any(os.environ.get(k) for k in keys):
            return name
    return "local"


def _construct(choice: str, api_key: str | None, model: str | None) -> Provider:
    model = model or os.environ.get("ASKWAREHOUSE_MODEL") or DEFAULT_MODELS.get(choice)

    if choice == "local":
        from askwarehouse.providers.local import LocalProvider
        return LocalProvider()
    if choice == "gemini":
        from askwarehouse.providers.hosted import GeminiProvider
        return GeminiProvider(model=model, api_key=api_key)
    if choice == "groq":
        from askwarehouse.providers.hosted import GroqProvider
        return GroqProvider(model=model, api_key=api_key)
    if choice == "anthropic":
        from askwarehouse.providers.hosted import AnthropicProvider
        return AnthropicProvider(model=model, api_key=api_key)
    if choice == "openai":
        from askwarehouse.providers.hosted import OpenAIProvider
        return OpenAIProvider(model=model, api_key=api_key)
    raise ValueError(f"unknown provider: {choice}")


def get_provider(name: str | None = None, api_key: str | None = None,
                 model: str | None = None) -> Provider:
    """name: 'local' | 'gemini' | 'groq' | 'anthropic' | 'openai' | None (auto)."""
    choice = name or os.environ.get("ASKWAREHOUSE_PROVIDER") or _auto_choice()

    if api_key:  # bring-your-own-key: never cache
        return _construct(choice, api_key, model)

    cache_key = f"{choice}:{model or ''}"
    if cache_key not in _cached:
        _cached[cache_key] = _construct(choice, None, model)
    return _cached[cache_key]
