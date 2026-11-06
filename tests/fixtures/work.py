"""Explicitly dated work, distinct from historical inventory in synthetic projects."""

from pathlib import Path

from digest.config import Config
from tests.fixtures.make_projects import _kanvas

CURRENT = "2026-11-04T18:00:00+00:00"


def add_current_work(config: Config, *, extra_result: bool = True) -> None:
    kanvas = _kanvas()
    kanvas.now_iso = lambda: CURRENT
    for project in config.projects:

        def add(board):
            kanvas.add_note(
                kanvas.find_task(board, "AN-01"),
                "Contraste actual documentado; conserva controles y límites.",
                "fixture-agent",
            )
            if extra_result:
                task = kanvas.add_task(
                    board,
                    "Comprobar el control actual",
                    board["groups"][0],
                    state="done",
                    by="fixture-agent",
                )
                kanvas.add_note(
                    task, "Control actual disponible; interpretación pendiente.", "fixture-agent"
                )

        kanvas.mutate(str(Path(project.root) / "kanvas.json"), add)
