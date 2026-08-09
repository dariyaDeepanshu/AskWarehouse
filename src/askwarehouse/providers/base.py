from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    provider: str = ""
    model: str = ""


class Provider(ABC):
    """Every stage of the pipeline that touches an LLM (ambiguity check,
    planner, SQL generation, self-critique, NL answer) goes through this
    interface, so the eval harness can swap providers without touching
    pipeline code -- this is what makes the cost/accuracy comparison in the
    eval table possible."""

    name: str = "base"

    @abstractmethod
    def generate(self, system: str, user: str, max_tokens: int = 800,
                 temperature: float = 0.0) -> LLMResponse:
        ...
