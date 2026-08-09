"""Pluggable hosted providers. Not used by default in this environment (no
API key present), but wired to the same Provider interface as local.py so
that dropping ANTHROPIC_API_KEY / OPENAI_API_KEY into .env is enough to
switch -- e.g. for the cost/accuracy comparison the eval table asks for.
Implemented as plain HTTP calls (no SDK dependency) since these paths are
optional."""
import os
import time
import requests

from askwarehouse.providers.base import Provider, LLMResponse


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-5", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

    def generate(self, system: str, user: str, max_tokens: int = 800,
                 temperature: float = 0.0) -> LLMResponse:
        t0 = time.perf_counter()
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        usage = data.get("usage", {})
        return LLMResponse(
            text=text.strip(),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
            provider="anthropic",
            model=self.model,
        )


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model: str = "gpt-4.1", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

    def generate(self, system: str, user: str, max_tokens: int = 800,
                 temperature: float = 0.0) -> LLMResponse:
        t0 = time.perf_counter()
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            text=text.strip(),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
            provider="openai",
            model=self.model,
        )
