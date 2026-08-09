"""Picks a Provider based on what's available. Local (free, no key) is the
default and what this environment actually runs on. Dropping
ANTHROPIC_API_KEY or OPENAI_API_KEY into .env is enough to switch -- no
other code changes -- which is what the eval harness uses for the
cost/accuracy comparison."""
import os
from dotenv import load_dotenv

from askwarehouse.providers.base import Provider

load_dotenv()

_cached: dict[str, Provider] = {}


def get_provider(name: str | None = None) -> Provider:
    """name: 'local' | 'anthropic' | 'openai' | None (auto: prefer an
    explicitly requested hosted key if present, else local)."""
    choice = name or os.environ.get("ASKWAREHOUSE_PROVIDER")
    if choice is None:
        if os.environ.get("ANTHROPIC_API_KEY"):
            choice = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            choice = "openai"
        else:
            choice = "local"

    if choice in _cached:
        return _cached[choice]

    if choice == "local":
        from askwarehouse.providers.local import LocalProvider
        provider = LocalProvider()
    elif choice == "anthropic":
        from askwarehouse.providers.hosted import AnthropicProvider
        provider = AnthropicProvider()
    elif choice == "openai":
        from askwarehouse.providers.hosted import OpenAIProvider
        provider = OpenAIProvider()
    else:
        raise ValueError(f"unknown provider: {choice}")

    _cached[choice] = provider
    return provider
