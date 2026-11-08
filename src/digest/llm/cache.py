"""Immutable private nodes, keyed by exact inputs and revalidated on every reuse."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from itertools import islice
from pathlib import Path
from typing import Any
from uuid import uuid4

from digest.collectors.base import canonical, content_hash
from digest.config import Config
from digest.publish.files import create, destination
from digest.util.fs import read_bounded

VERSION = "1"
MAX_NODE_BYTES = 4_000_000


@dataclass(frozen=True)
class Cached:
    value: Any
    provider: str
    model: str


class Nodes:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.root = destination(config, Path(config.paths.data_dir), "nodes")

    def key(
        self,
        task: str,
        project_ids: set[str],
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        prompt_name: str,
        prompt_version: str,
        package: dict[str, Any] | None = None,
    ) -> str:
        validators = b"".join(
            files("digest.llm").joinpath(name).read_bytes()
            for name in ("validator.py", "schemas.py", "grounding.py")
        )
        scope = {
            p.id: {"external_allowed": p.external_allowed}
            for p in self.config.projects
            if p.id in project_ids
        }
        routes = getattr(self.config.llm.routing, task)
        providers = {
            name: {
                "base_url": self.config.llm.providers[name].base_url,
                "model": self.config.llm.providers[name].model,
            }
            for name in routes
        }
        return content_hash(
            canonical(
                {
                    "version": VERSION,
                    "task": task,
                    "scope": scope,
                    "routes": routes,
                    "providers": providers,
                    "messages": messages,
                    "schema": schema,
                    "prompt_name": prompt_name,
                    "prompt_version": prompt_version,
                    "validator": content_hash(validators),
                    "input_hash": content_hash(canonical(package)) if package is not None else None,
                }
            )
        )

    def directory(self, key: str) -> Path:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid node key")
        return destination(self.config, self.root, key[:2] + "/" + key)

    def load(
        self, key: str, validate: Callable[[dict[str, Any]], Any], input_hash: str | None = None
    ) -> Cached | None:
        directory = self.directory(key)
        if not directory.exists():
            return None
        # Only a bounded number of immutable variants is considered; corrupt nodes
        # are never overwritten and cannot masquerade as validated progress.
        candidates = sorted(
            islice(directory.glob("*.json"), 64), key=lambda p: p.lstat().st_mtime_ns, reverse=True
        )
        for path in candidates[:8]:
            try:
                raw = read_bounded(self.root, path.relative_to(self.root), max_bytes=MAX_NODE_BYTES)
                node = json.loads(raw)
                if node["version"] != VERSION or node["key"] != key:
                    continue
                if node.get("input_hash") != input_hash:
                    continue
                if input_hash is not None and content_hash(canonical(node["input"])) != input_hash:
                    continue
                provider = self.config.llm.providers.get(node["provider"])
                if provider is None or provider.model != node["model"]:
                    continue
                value = validate(node["value"])
                return Cached(value, node["provider"], node["model"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return None

    def save(
        self,
        key: str,
        value: dict[str, Any],
        provider: str,
        model: str,
        package: dict[str, Any] | None = None,
    ) -> None:
        node = {
            "version": VERSION,
            "key": key,
            "provider": provider,
            "model": model,
            "value": value,
            "input": package,
            "input_hash": content_hash(canonical(package)) if package is not None else None,
        }
        raw = canonical(node).encode()
        if len(raw) > MAX_NODE_BYTES:
            raise ValueError("Validated node exceeds storage limit")
        create(self.directory(key) / (uuid4().hex + ".json"), raw)
