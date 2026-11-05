"""Capture execution logs and optional Slurm accounting without running workloads."""

import csv
import io
from datetime import datetime
from pathlib import Path

from digest.collectors.base import (
    CaptureContext,
    CollectorOutput,
    EvidenceDraft,
    Omission,
    canonical,
    content_hash,
    utc,
)
from digest.collectors.files import discover
from digest.collectors.kanvas import event_time
from digest.config import ProjectConfig
from digest.util.fs import ReadError, read_bounded
from digest.util.proc import ProcessError, run


class RunsCollector:
    source = "runs"
    phase = 1

    def collect(
        self, project: ProjectConfig, since: datetime | None, ctx: CaptureContext
    ) -> CollectorOutput:
        previous = (ctx.previous_payload or {}).get("logs", {})
        payload = {}
        omitted = []
        evidence = []
        files, errors = discover(project, ctx, project.runs.logs)
        omitted.extend(errors)
        for name in files:
            try:
                ctx.remaining()
                raw = read_bounded(
                    Path(project.root),
                    name,
                    exclude=project.exclude,
                    max_bytes=ctx.limits.max_file_bytes,
                )
                hashed = content_hash(raw)
                payload[name] = hashed
                if previous.get(name) == hashed:
                    continue
                lines = raw.decode("utf-8", errors="replace").splitlines()
                tail = lines[-80:]
                excerpt = "\n".join(tail)
                event = event_time(tail[-1].split(" ", 1)[0]) if tail else None
                if since and event and event < since:
                    continue
                lower = excerpt.lower()
                kind = (
                    "run_error"
                    if any(marker in lower for marker in ["error", "failed", "traceback", "fatal"])
                    else "run"
                )
                if len(excerpt) > ctx.limits.max_excerpt_chars or len(lines) > 80:
                    omitted.append(Omission(name, "log_truncated"))
                evidence.append(
                    EvidenceDraft(
                        kind,
                        name,
                        raw,
                        excerpt[-ctx.limits.max_excerpt_chars :],
                        ctx.observed_at,
                        event,
                        {"path": name, "source": "log", "has_warning": "warning" in lower},
                    )
                )
            except (ReadError, OSError, TimeoutError) as error:
                reason = str(error) if isinstance(error, ReadError) else "log_unreadable"
                if reason != "excluded":
                    omitted.append(Omission(name, reason))
        seen = []
        if project.runs.slurm.enabled:
            try:
                args = [
                    "sacct",
                    "-u",
                    project.runs.slurm.user,
                    "-S",
                    utc(
                        since or ctx.observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
                    ),
                    "-E",
                    utc(ctx.observed_at),
                    "-X",
                    "-P",
                    "-o",
                    "JobID,JobName,State,ExitCode,Elapsed,Start,End,WorkDir",
                ]
                result = run(args, timeout=ctx.remaining())
                if result.returncode:
                    raise ProcessError("sacct_failed")
                if len(result.stdout) > ctx.limits.max_file_bytes:
                    raise ValueError("sacct_too_large")
                for row in csv.DictReader(io.StringIO(result.stdout), delimiter="|"):
                    workdir = row.get("WorkDir")
                    if (
                        not workdir
                        or not Path(workdir).is_absolute()
                        or not Path(workdir).resolve().is_relative_to(Path(project.root).resolve())
                    ):
                        continue
                    job = row["JobID"]
                    state = row["State"]
                    value = canonical({k: v for k, v in row.items() if k})
                    hashed = content_hash(value)
                    seen.append(hashed)
                    if hashed in (ctx.previous_payload or {}).get("jobs", []):
                        continue
                    # sacct dates lack an offset in the documented output: do not invent a timezone.
                    event = event_time(row.get("End")) or event_time(row.get("Start"))
                    kind = (
                        "run"
                        if state == "COMPLETED"
                        else "run_error"
                        if state in {"FAILED", "TIMEOUT", "CANCELLED", "OUT_OF_MEMORY", "NODE_FAIL"}
                        else "run"
                    )
                    evidence.append(
                        EvidenceDraft(
                            kind,
                            "slurm:" + job,
                            value,
                            value[: ctx.limits.max_excerpt_chars],
                            ctx.observed_at,
                            event,
                            {
                                "source": "slurm",
                                "job_id": job,
                                "state": state,
                                "exit_code": row.get("ExitCode"),
                            },
                        )
                    )
            except (ProcessError, ValueError, OSError, KeyError, TimeoutError):
                omitted.append(Omission("slurm", "sacct_unavailable"))
        return CollectorOutput(
            evidence, "partial" if omitted else "ok", omitted, {"logs": payload, "jobs": seen}
        )
