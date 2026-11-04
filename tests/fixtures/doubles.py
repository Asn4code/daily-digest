"""Deterministic local doubles for provider, scheduler, SMTP and storage tests."""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from aiosmtpd.controller import Controller

from digest.util.proc import ProcessResult, run


class FakeLLM:
    """Produce extraction-shaped JSON from the supplied evidence package only."""

    def __init__(self, mode: Literal["good", "liar", "down", "broken_json"] = "good") -> None:
        if mode not in {"good", "liar", "down", "broken_json"}:
            raise ValueError("Unknown FakeLLM mode")
        self.mode = mode
        self.calls = 0

    def generate(self, package: dict[str, Any]) -> str:
        self.calls += 1
        if self.mode == "down":
            raise TimeoutError("Synthetic provider timeout")
        if self.mode == "broken_json" and self.calls == 1:
            return '{"result_id":'
        evidence = package["evidence"]
        facts = [{"text": item["excerpt"], "evidence": [item["id"]]} for item in evidence]
        numbers = [
            {
                "name": number["name"],
                "value": number["value"],
                "unit": number.get("unit"),
                "evidence": item["id"],
            }
            for item in evidence
            for number in item.get("numbers", [])
        ]
        if self.mode == "liar":
            facts.append({"text": "Cifra inventada: 987654321", "evidence": ["ev_invented"]})
            numbers.append(
                {"name": "invented", "value": 987654321, "unit": None, "evidence": "ev_invented"}
            )
        return json.dumps(
            {
                "result_id": package["result_id"],
                "summary": evidence[0]["excerpt"] if evidence else "Sin evidencias verificables.",
                "facts": facts,
                "numbers": numbers,
                "interpretations": [],
                "uncertainties": [],
                "controls_and_parameters": [],
                "failures_or_blockers": [],
                "open_threads": [],
            },
            ensure_ascii=False,
        )


class FakeSacct:
    """Return the configured sacct -P column layout with fixed UTC job dates."""

    def run(self, args: list[str]) -> ProcessResult:
        if not args or args[0] != "sacct":
            raise ValueError("Expected sacct")
        return ProcessResult(
            0,
            "JobID|JobName|State|ExitCode|Elapsed|Start|End|WorkDir|\n"
            "1001|control|COMPLETED|0:0|00:10:00|2026-11-02T10:00:00|2026-11-02T10:10:00|/synthetic/proj-ok|\n"
            "1002|candidate|FAILED|1:0|00:01:00|2026-11-03T18:00:00|2026-11-03T18:01:00|/synthetic/proj-fail|\n",
            "",
        )


@dataclass
class FrozenClock:
    instant: datetime = datetime(2026, 11, 3, 20, tzinfo=UTC)

    def now(self) -> datetime:
        if self.instant.tzinfo is None:
            raise ValueError("Clock requires an aware datetime")
        return self.instant.astimezone(UTC)

    def advance(self, delta: timedelta) -> None:
        self.instant += delta


class _EphemeralController(Controller):
    async def _create_server(self) -> asyncio.AbstractServer:
        server = await super()._create_server()
        self.port = server.sockets[0].getsockname()[1]
        return server


class LocalSMTP:
    """Capture mail on loopback, optionally disconnect after storing DATA."""

    def __init__(self, *, disconnect_after_data: bool = False) -> None:
        self.disconnect_after_data = disconnect_after_data
        self.messages: list[bytes] = []
        self.controller = _EphemeralController(self, hostname="127.0.0.1", port=0)

    @property
    def port(self) -> int:
        return int(self.controller.port)

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        self.messages.append(envelope.original_content)
        if self.disconnect_after_data:
            server.transport.close()
        return "250 Accepted"

    def __enter__(self) -> "LocalSMTP":
        self.controller.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.controller.stop()


@dataclass
class LocalDrive:
    """Use an actual rclone local remote, never a cloud credential."""

    root: Path
    offline: bool = False

    @property
    def remote(self) -> str:
        return "digest_fixture_missing_remote:" if self.offline else f":local:{self.root}"

    def copy(self, source: Path) -> ProcessResult:
        return run(
            [
                "rclone",
                "--config",
                "/dev/null",
                "copy",
                "--immutable",
                "--retries",
                "1",
                "--low-level-retries",
                "1",
                str(source),
                self.remote,
            ],
            timeout=15,
        )
