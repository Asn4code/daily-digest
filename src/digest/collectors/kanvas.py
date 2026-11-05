"""Read bounded Kanvas boards and compare verified snapshots."""

import json
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from digest.collectors.base import (
    CaptureContext,
    CollectorOutput,
    EvidenceDraft,
    Omission,
    canonical,
    content_hash,
)
from digest.config import ProjectConfig
from digest.util.fs import ReadError, read_bounded
from digest.util.proc import ProcessError, run


def event_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value)
        return date.astimezone(UTC) if date.tzinfo else None
    except ValueError:
        return None


class KanvasCollector:
    source = "kanvas"
    phase = 1

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        try:
            ctx.remaining()
            raw = read_bounded(
                Path(project.root),
                project.kanvas,
                exclude=project.exclude,
                max_bytes=ctx.limits.max_file_bytes,
            )
            board = json.loads(raw)
            if (
                not isinstance(board, dict)
                or type(board.get("kanvas")) is not int
                or board["kanvas"] != 1
            ):
                return CollectorOutput(
                    status="partial", omitted=[Omission(project.kanvas, "unsupported_schema")]
                )
            # Validate exactly the bytes read, not a second project path open by the CLI.
            # The temporary directory belongs to the service, outside the observed project.
            if ctx.data_dir.resolve().is_relative_to(Path(project.root).resolve()):
                raise ReadError("output_inside_project")
            ctx.data_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="kanvas-check-", dir=ctx.data_dir) as temp:
                path = Path(temp) / "kanvas.json"
                path.write_bytes(raw)
                result = run(
                    [*ctx.kanvas_command, "check", "-b", str(path)], timeout=ctx.remaining()
                )
            if result.returncode:
                return CollectorOutput(
                    status="failed", omitted=[Omission(project.kanvas, "kanvas_check_failed")]
                )
            tasks = board.get("tasks", [])
            if not isinstance(tasks, list) or any(not isinstance(t, dict) for t in tasks):
                raise ValueError("invalid_board")
            previous = (ctx.previous_payload or {}).get("tasks", {})
            evidence = []
            sequences = dict((ctx.previous_payload or {}).get("transition_sequences", {}))
            payload: dict[str, Any] = {"tasks": {}, "transition_sequences": sequences}
            for task in tasks:
                ctx.remaining()
                ident = task["id"]
                old = previous.get(ident, {})
                state = task["state"]
                payload["tasks"][ident] = task
                if old.get("state") != state:
                    sequence = sequences.get(ident, 0) + 1
                    sequences[ident] = sequence
                    content = canonical({"id": ident, "state": state, "sequence": sequence})
                    evidence.append(
                        EvidenceDraft(
                            "task_transition",
                            ident + "#state",
                            content,
                            f"{ident}: {task['title']} [{state}]"[: ctx.limits.max_excerpt_chars],
                            ctx.observed_at,
                            meta={
                                "title": task["title"],
                                "state": state,
                                "previous_state": old.get("state"),
                                "by": task.get("by"),
                            },
                            task_id=ident,
                        )
                    )
                old_notes = Counter(canonical(n) for n in old.get("notes", []))
                occurrences: Counter[str] = Counter()
                for note in task.get("notes", []):
                    key = canonical(note)
                    occurrences[key] += 1
                    if occurrences[key] <= old_notes[key]:
                        continue
                    event = event_time(note.get("edited") or note.get("at"))
                    if since is not None and event is not None and event < since:
                        continue
                    text = note["text"]
                    evidence.append(
                        EvidenceDraft(
                            "task_question" if text.startswith("Question:") else "task_note",
                            f"{ident}#note/{content_hash(key)[:20]}/{occurrences[key]}",
                            key,
                            text[: ctx.limits.max_excerpt_chars],
                            ctx.observed_at,
                            event,
                            {"by": note.get("by"), "title": task["title"], "state": state},
                            ident,
                        )
                    )
            return CollectorOutput(evidence=evidence, snapshot_payload=payload)
        except ReadError as error:
            return CollectorOutput(status="failed", omitted=[Omission(project.kanvas, str(error))])
        except (OSError, ValueError, TypeError, KeyError, ProcessError, TimeoutError):
            return CollectorOutput(
                status="failed", omitted=[Omission(project.kanvas, "kanvas_unavailable")]
            )
