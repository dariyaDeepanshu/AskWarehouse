"""Pluggable hosted providers, all on the same Provider interface as
local.py so a single env var swaps the whole pipeline's backend.

The Vercel deployment defaults to a free-tier hosted model (Gemini or Groq)
since there is no GPU to run the local Qwen model on. Implemented as plain
HTTP calls (no SDK dependency) so these paths add nothing to the serverless
bundle."""
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


class OpenAICompatibleProvider(Provider):
    """OpenAI Chat Completions wire format. Works for OpenAI itself and for
    any compatible endpoint (Groq, Together, OpenRouter, a local vLLM) via
    ``base_url``."""
    name = "openai"

    def __init__(self, model: str = "gpt-4.1", api_key: str | None = None,
                 base_url: str = "https://api.openai.com/v1", env_key: str = "OPENAI_API_KEY"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get(env_key)
        if not self.api_key:
            raise RuntimeError(f"{env_key} not set")

    def generate(self, system: str, user: str, max_tokens: int = 800,
                 temperature: float = 0.0) -> LLMResponse:
        t0 = time.perf_counter()
        resp = requests.post(
            f"{self.base_url}/chat/completions",
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
            text=(text or "").strip(),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
            provider=self.name,
            model=self.model,
        )


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"

    def __init__(self, model: str = "gpt-4.1", api_key: str | None = None):
        super().__init__(model=model, api_key=api_key,
                         base_url="https://api.openai.com/v1", env_key="OPENAI_API_KEY")


class GroqProvider(OpenAICompatibleProvider):
    """Groq's free tier -- OpenAI-compatible, very fast. Good default models
    for SQL: llama-3.3-70b-versatile, openai/gpt-oss-120b."""
    name = "groq"

    def __init__(self, model: str = "llama-3.3-70b-versatile", api_key: str | None = None):
        super().__init__(model=model, api_key=api_key,
                         base_url="https://api.groq.com/openai/v1", env_key="GROQ_API_KEY")


class GeminiProvider(Provider):
    """Google's Gemini API. The free tier is generous on tokens-per-minute,
    which matters here because one question fans out to 5-8 LLM calls."""
    name = "gemini"

    def __init__(self, model: str = "gemini-2.0-flash", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set")

    def generate(self, system: str, user: str, max_tokens: int = 800,
                 temperature: float = 0.0) -> LLMResponse:
        t0 = time.perf_counter()
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"content-type": "application/json", "x-goog-api-key": self.api_key},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        text = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", []) or []
            text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text=text.strip(),
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
            provider="gemini",
            model=self.model,
        )
