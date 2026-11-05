"""Remove credential values and common credential syntax from untrusted text."""

import re


def redact(text: str, secret_values: tuple[str, ...] = ()) -> str:
    for value in sorted(secret_values, key=len, reverse=True):
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
