from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import quantiles

from .models import Usage


@dataclass(slots=True)
class TokenSample:
    seat_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(slots=True)
class TokenMonitor:
    window_size: int = 200
    samples: deque[TokenSample] = field(default_factory=lambda: deque(maxlen=200))

    def record(self, seat_id: str, model: str, usage: Usage) -> None:
        self.samples.append(
            TokenSample(
                seat_id=seat_id,
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
        )

    def stats(self) -> dict[str, float]:
        if not self.samples:
            return {
                "calls": 0,
                "avg_prompt": 0.0,
                "avg_completion": 0.0,
                "avg_total": 0.0,
                "p95_total": 0.0,
                "required_context_capacity": 2048.0,
            }

        prompts = [s.prompt_tokens for s in self.samples]
        completions = [s.completion_tokens for s in self.samples]
        totals = [s.total_tokens for s in self.samples]

        p95_total = self._p95(totals)
        required_capacity = max(2048.0, p95_total * 1.35 + 512.0)

        return {
            "calls": float(len(self.samples)),
            "avg_prompt": sum(prompts) / len(prompts),
            "avg_completion": sum(completions) / len(completions),
            "avg_total": sum(totals) / len(totals),
            "p95_total": p95_total,
            "required_context_capacity": required_capacity,
        }

    def context_warning(self, model_context_window: int) -> str | None:
        s = self.stats()
        required = s["required_context_capacity"]
        if required > model_context_window:
            return (
                f"required_context_capacity={required:.0f} exceeds model_context_window={model_context_window}. "
                "Reduce prompt size, summary depth, or switch to a larger-context model."
            )
        utilization = required / max(1.0, float(model_context_window))
        if utilization > 0.8:
            return (
                f"context utilization high ({utilization:.0%}); consider reducing retained memory or "
                "lowering max output tokens."
            )
        return None

    def recommended_max_output_tokens(self, model_context_window: int) -> int:
        s = self.stats()
        required = s["required_context_capacity"]
        headroom = max(128.0, float(model_context_window) - required)
        return int(min(768.0, max(128.0, headroom * 0.45)))

    def stats_by_model(self) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[TokenSample]] = {}
        for sample in self.samples:
            grouped.setdefault(sample.model, []).append(sample)

        out: dict[str, dict[str, float]] = {}
        for model, items in grouped.items():
            prompts = [s.prompt_tokens for s in items]
            completions = [s.completion_tokens for s in items]
            totals = [s.total_tokens for s in items]
            p95_total = self._p95(totals)
            out[model] = {
                "calls": float(len(items)),
                "avg_prompt": sum(prompts) / len(prompts),
                "avg_completion": sum(completions) / len(completions),
                "avg_total": sum(totals) / len(totals),
                "p95_total": p95_total,
                "required_context_capacity": max(2048.0, p95_total * 1.35 + 512.0),
            }
        return out

    @staticmethod
    def _p95(values: list[int]) -> float:
        if len(values) == 1:
            return float(values[0])
        return float(quantiles(values, n=20, method="inclusive")[-1])
