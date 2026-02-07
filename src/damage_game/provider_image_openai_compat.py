from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(slots=True)
class OpenAICompatibleImageConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: float = 45.0


class OpenAICompatibleImageClient:
    def __init__(self, cfg: OpenAICompatibleImageConfig) -> None:
        self.cfg = cfg
        self._endpoint = cfg.base_url.rstrip("/") + "/images/generations"

    def generate_png(self, prompt: str, size: str = "512x512", model: str | None = None) -> bytes | None:
        chosen_model = (model or self.cfg.model).strip()
        request_body = {
            "model": chosen_model,
            "prompt": prompt,
            "size": size,
            "response_format": "b64_json",
        }
        payload = self._post(request_body)
        item = (payload.get("data") or [{}])[0]
        if not isinstance(item, dict):
            return None

        b64 = item.get("b64_json")
        if isinstance(b64, str) and b64.strip():
            try:
                return base64.b64decode(b64)
            except Exception:
                return None

        url = item.get("url")
        if isinstance(url, str) and url.strip():
            return self._get_bytes(url.strip())
        return None

    def _post(self, request_body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        data = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(self._endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"image provider HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"image provider connection error: {exc.reason}") from exc
        return json.loads(raw)

    def _get_bytes(self, url: str) -> bytes | None:
        headers = {}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                return resp.read()
        except Exception:
            return None
