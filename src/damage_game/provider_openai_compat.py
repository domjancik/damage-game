from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .models import ProviderResponse, Usage


@dataclass(slots=True)
class OpenAICompatibleConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: float = 30.0


class OpenAICompatibleClient:
    def __init__(self, cfg: OpenAICompatibleConfig) -> None:
        self.cfg = cfg
        self._endpoint = cfg.base_url.rstrip("/") + "/chat/completions"

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 350,
        model: str | None = None,
    ) -> ProviderResponse:
        chosen_model = model or self.cfg.model
        base_request = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens,
        }
        request_variants = [
            {
                **base_request,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "action_response",
                        "schema": {"type": "object"},
                        "strict": False,
                    },
                },
            },
            {**base_request, "response_format": {"type": "text"}},
            base_request,
        ]

        payload = None
        elapsed_ms = 0.0
        last_error = None
        for request_body in request_variants:
            try:
                payload, elapsed_ms = self._post(request_body)
                break
            except RuntimeError as exc:
                last_error = exc
                continue

        if payload is None:
            raise RuntimeError(str(last_error) if last_error else "provider request failed")

        content = payload["choices"][0]["message"]["content"]
        usage_obj = payload.get("usage", {})
        usage = Usage(
            prompt_tokens=int(usage_obj.get("prompt_tokens", 0)),
            completion_tokens=int(usage_obj.get("completion_tokens", 0)),
            total_tokens=int(usage_obj.get("total_tokens", 0)),
        )
        model = str(payload.get("model", chosen_model))

        return ProviderResponse(content=content, usage=usage, model=model, latency_ms=elapsed_ms)

    def _post(self, request_body: dict) -> tuple[dict, float]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        data = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(self._endpoint, data=data, headers=headers, method="POST")

        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"provider HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"provider connection error: {exc.reason}") from exc

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return json.loads(raw), elapsed_ms

    def list_models(self) -> list[str]:
        endpoint = self.cfg.base_url.rstrip("/") + "/models"
        headers = {}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        req = urllib.request.Request(endpoint, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"provider HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"provider connection error: {exc.reason}") from exc

        return [item["id"] for item in payload.get("data", []) if "id" in item]
