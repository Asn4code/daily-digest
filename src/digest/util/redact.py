"""Remove credential values and common credential syntax from untrusted text."""

import html
import json
import re
from typing import Any

from digest.config import Config
from digest.doctor import _credential


def redact(text: str, secret_values: tuple[str, ...] = ()) -> str:
    variants = set(secret_values)
    for _ in range(3):
        variants.update(json.dumps(value, ensure_ascii=False)[1:-1] for value in tuple(variants))
        variants.update(html.escape(value, quote=True) for value in tuple(variants))
    for value in sorted(variants, key=len, reverse=True):
        if value:
            text = text.replace(value, "[redactado]")
    text = re.sub(
        r'(?i)([\w.-]*(?:api[_-]?key|password|secret|token)[\w.-]*["\x27]?\s*[=:]\s*)'
        r'(?:"[^"\n]*"|\x27[^\x27\n]*\x27|[^\s,;]+)',
        r"\1[redactado]",
        text,
    )
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9_.~+/-]+=*", "Bearer [redactado]", text)
    return re.sub(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}", "[redactado]", text)


def redact_tree(value: Any, secret_values: tuple[str, ...] = ()) -> Any:
    """Sanitize structured data before serialization, including dictionary keys."""
    if isinstance(value, str):
        return redact(value, secret_values)
    if isinstance(value, dict):
        sensitive = {
            "api_key",
            "apikey",
            "password",
            "smtp_password",
            "secret",
            "access_token",
            "refresh_token",
            "authorization",
            "token",
        }
        return {
            redact(str(key), secret_values): (
                "[redactado]"
                if str(key).lower().replace("-", "_") in sensitive
                else redact_tree(item, secret_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_tree(item, secret_values) for item in value]
    return value


def known_secrets(config: Config) -> tuple[str, ...]:
    names = [p.api_key_env for p in config.llm.providers.values()]
    names.append(config.email.password_env)
    return tuple(value for name in names if (value := _credential(name)))
