"""Per-request LLM usage collection + optional per-request model override.

Both are context variables so concurrent requests never see each other's
data, and code that never sets them behaves exactly as before."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

model_override_var: ContextVar[str | None] = ContextVar("llm_model_override", default=None)
usage_collector_var: ContextVar["UsageCollector | None"] = ContextVar("llm_usage_collector", default=None)


@dataclass
class UsageCollector:
    calls: int = 0
    input_tokens: int | None = None      # None until the provider reports counts
    output_tokens: int | None = None
    models: list[str] = field(default_factory=list)

    # AI availability/failover telemetry. These fields are deliberately
    # request-scoped so concurrent customers cannot see each other's state.
    attempts: int = 0
    retry_count: int = 0
    fallback_used: bool = False
    fallback_models: list[str] = field(default_factory=list)
    transient_errors: int = 0
    failover_exhausted: bool = False

    def record_attempt(
        self,
        model: str,
        *,
        retry: bool = False,
        fallback: bool = False,
        transient_error: bool = False,
    ) -> None:
        self.attempts += 1
        if retry:
            self.retry_count += 1
        if fallback:
            self.fallback_used = True
            if model and model not in self.fallback_models:
                self.fallback_models.append(model)
        if transient_error:
            self.transient_errors += 1

    def add(self, model: str, response) -> None:
        self.calls += 1
        if model and model not in self.models:
            self.models.append(model)
        meta = getattr(response, "usage_metadata", None)
        if meta is None:
            return
        prompt = getattr(meta, "prompt_token_count", None)
        out = getattr(meta, "candidates_token_count", None)
        if isinstance(prompt, int):
            self.input_tokens = (self.input_tokens or 0) + prompt
        if isinstance(out, int):
            self.output_tokens = (self.output_tokens or 0) + out

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)
