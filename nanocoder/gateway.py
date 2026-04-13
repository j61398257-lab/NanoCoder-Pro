"""Gateway — multi-model routing and automatic fallback.

Inspired by:
  - LiteLLM's unified interface (100+ providers behind one API)
  - OpenRouter's smart routing and fallback
  - RouteLLM's intent-based model selection

Supports:
  - Task-based routing (fast model for simple tasks, strong model for complex ones)
  - Automatic fallback when a provider returns an error
  - Cost / latency tracking per provider
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from .llm import LLM, LLMResponse


@dataclass
class ModelProfile:
    name: str
    api_key: str
    base_url: str | None = None
    tier: str = "default"  # "fast" | "default" | "strong"
    max_tokens: int = 4096
    temperature: float = 0.0
    total_calls: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0


class Gateway:
    """Route requests across multiple models with automatic fallback."""

    def __init__(self, profiles: list[ModelProfile] | None = None):
        self._profiles: list[ModelProfile] = profiles or []
        self._llm_cache: dict[str, LLM] = {}

    def add_profile(self, profile: ModelProfile):
        self._profiles.append(profile)

    def get_llm(self, model_name: str) -> LLM:
        """Get or create an LLM instance for the specified model."""
        if model_name in self._llm_cache:
            return self._llm_cache[model_name]

        profile = self._find_profile(model_name)
        if not profile:
            raise ValueError(f"No profile found for model '{model_name}'")

        llm = LLM(
            model=profile.name,
            api_key=profile.api_key,
            base_url=profile.base_url,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
        )
        self._llm_cache[model_name] = llm
        return llm

    def route(self, task_hint: str = "default") -> LLM:
        """Select the best model for the task tier.

        task_hint: "fast" for simple queries, "strong" for complex tasks, "default" otherwise.
        """
        candidates = [p for p in self._profiles if p.tier == task_hint]
        if not candidates:
            candidates = [p for p in self._profiles if p.tier == "default"]
        if not candidates:
            candidates = self._profiles

        if not candidates:
            raise ValueError("No model profiles configured in Gateway")

        best = min(candidates, key=lambda p: p.total_errors)
        return self.get_llm(best.name)

    def chat_with_fallback(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_token=None,
        tier: str = "default",
    ) -> tuple[LLMResponse, str]:
        """Try routing to the preferred tier, fallback on failure.

        Returns (response, model_name_used).
        """
        ordered = self._ranked_for_tier(tier)

        last_error: Exception | None = None
        for profile in ordered:
            llm = self.get_llm(profile.name)
            t0 = time.time()
            try:
                resp = llm.chat(messages=messages, tools=tools, on_token=on_token)
                elapsed = (time.time() - t0) * 1000
                profile.total_calls += 1
                profile.avg_latency_ms = (
                    (profile.avg_latency_ms * (profile.total_calls - 1) + elapsed)
                    / profile.total_calls
                )
                return resp, profile.name
            except Exception as e:
                profile.total_errors += 1
                last_error = e
                continue

        raise RuntimeError(
            f"All {len(ordered)} model(s) failed. Last error: {last_error}"
        )

    def _ranked_for_tier(self, tier: str) -> list[ModelProfile]:
        """Rank profiles: preferred tier first, then others as fallback."""
        preferred = [p for p in self._profiles if p.tier == tier]
        others = [p for p in self._profiles if p.tier != tier]
        preferred.sort(key=lambda p: p.total_errors)
        others.sort(key=lambda p: p.total_errors)
        return preferred + others

    def _find_profile(self, model_name: str) -> ModelProfile | None:
        for p in self._profiles:
            if p.name == model_name:
                return p
        return None

    def list_profiles(self) -> list[ModelProfile]:
        return list(self._profiles)

    def stats(self) -> str:
        """Format gateway statistics as a readable string."""
        if not self._profiles:
            return "No models configured."
        lines = ["Gateway Model Stats:", ""]
        for p in self._profiles:
            lines.append(
                f"  {p.name} [{p.tier}] — "
                f"calls: {p.total_calls}, errors: {p.total_errors}, "
                f"latency: {p.avg_latency_ms:.0f}ms"
            )
        return "\n".join(lines)
