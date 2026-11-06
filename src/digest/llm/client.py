"""Bounded OpenAI-compatible requests without redirects or diagnostic payloads."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from digest.config import ProviderConfig
from digest.doctor import _credential


class ClientError(ValueError):
    """A stable code safe to persist; never contains HTTP bodies or credentials."""


@dataclass(frozen=True)
class Completion:
    value: dict[str, Any]
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0


Observer = Callable[[Completion | None, str | None, int], None]


def json_object(content: str) -> dict[str, Any]:
    start = content.find("{")
    if start >= 0:
        try:
            value, _ = json.JSONDecoder().raw_decode(content[start:])
            if isinstance(value, dict):
                return value
        except (ValueError, RecursionError):
            pass
    raise ClientError("invalid_json")


class Client:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.sleep = sleep

    def complete(
        self,
        provider: ProviderConfig,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        *,
        deadline: float,
        observer: Observer,
    ) -> Completion:
        key = _credential(provider.api_key_env)
        if not key:
            observer(None, "credential_missing", 0)
            raise ClientError("credential_missing")
        payload: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "digest_output", "strict": True, "schema": schema},
            }
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                observer(None, "generation_timeout", 0)
                raise ClientError("generation_timeout")
            started = time.monotonic()
            retryable = False
            code = "response_invalid"
            try:
                with httpx.Client(
                    transport=self.transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=min(provider.timeout_s, remaining),
                ) as client:
                    with client.stream(
                        "POST",
                        provider.base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + key},
                        json=payload,
                    ) as response:
                        if response.status_code != 200:
                            retryable = response.status_code == 429 or response.status_code >= 500
                            raise ClientError("http_" + str(response.status_code))
                        raw = bytearray()
                        for chunk in response.iter_bytes():
                            if time.monotonic() >= deadline:
                                raise ClientError("generation_timeout")
                            raw.extend(chunk)
                            if len(raw) > 2_000_000:
                                raise ClientError("response_too_large")
                envelope = json.loads(raw)
                content = envelope["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ClientError("response_invalid")
                value = json_object(content)
                usage = envelope.get("usage") or {}

                def tokens(name: str, counters: Any = usage) -> int | None:
                    n = counters.get(name)
                    return n if type(n) is int and n >= 0 else None

                duration = int((time.monotonic() - started) * 1000)
                result = Completion(
                    value, tokens("prompt_tokens"), tokens("completion_tokens"), duration
                )
                observer(result, None, duration)
                return result
            except httpx.TimeoutException:
                retryable = True
                code = "provider_timeout"
            except httpx.TransportError:
                retryable = True
                code = "transport_error"
            except ClientError as error:
                code = str(error)
            except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
                code = "response_invalid"
            duration = int((time.monotonic() - started) * 1000)
            observer(None, code, duration)
            if not retryable or attempt == 2:
                raise ClientError(code) from None
            delay = 0.25 * 2**attempt
            if time.monotonic() + delay >= deadline:
                observer(None, "generation_timeout", 0)
                raise ClientError("generation_timeout")
            self.sleep(delay)
        raise ClientError("provider_unavailable")
