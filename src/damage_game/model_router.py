from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ModelRoutingPolicy:
    primary_model: str
    fallback_models: list[str] = field(default_factory=list)


class ModelRouter:
    def __init__(self, policy: ModelRoutingPolicy) -> None:
        self.policy = policy
        self.available_models: set[str] = set()

    def set_available_models(self, models: list[str]) -> None:
        self.available_models = set(models)

    def pick_action_model(self, actor_tilt: float, actor_exposure: int) -> str:
        candidates = [self.policy.primary_model, *self.policy.fallback_models]
        routable = [m for m in candidates if (not self.available_models or m in self.available_models)]
        if not routable:
            return self.policy.primary_model

        high_pressure = actor_tilt >= 0.45 or actor_exposure >= 2
        if high_pressure:
            for model in routable:
                if "24b" in model.lower():
                    return model

        for model in routable:
            if "14b" in model.lower():
                return model
        return routable[0]

